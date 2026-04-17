"""
Servicos auxiliares para o no Webhook.

Concentra tres responsabilidades:

1. Resolucao de path (UUID ou path custom) -> Workflow + no webhook.
2. Autenticacao opcional configurada no no (none / header / basic / jwt).
3. Bus de notificacao em memoria para o botao "Listen for test event":
   um ``asyncio.Event`` por par (workflow_id, node_id) acordado quando a
   rota ``/webhook-test`` recebe uma requisicao; o endpoint ``/listen``
   aguarda o Event para retornar com latencia baixa.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.workflow import WebhookTestCapture, Workflow


# TTL de uma captura na tabela webhook_test_captures. O botao "Listen for
# test event" no frontend trabalha com timeout de ate 10 minutos; usamos
# um pouco mais para cobrir o janelamento da limpeza periodica.
CAPTURE_TTL_MINUTES = 15


# ---------------------------------------------------------------------------
# Bus de notificacao em memoria (por processo)
# ---------------------------------------------------------------------------

# Chave: (workflow_id_str, node_id). Valor: asyncio.Event criado sob demanda.
# Nao precisa de lock por tratar-se de cooperative scheduling (asyncio).
_CAPTURE_EVENTS: dict[tuple[str, str], asyncio.Event] = {}


def _event_key(workflow_id: UUID, node_id: str) -> tuple[str, str]:
    return (str(workflow_id), node_id)


def _get_or_create_event(workflow_id: UUID, node_id: str) -> asyncio.Event:
    key = _event_key(workflow_id, node_id)
    evt = _CAPTURE_EVENTS.get(key)
    if evt is None:
        evt = asyncio.Event()
        _CAPTURE_EVENTS[key] = evt
    return evt


def notify_capture(workflow_id: UUID, node_id: str) -> None:
    """Acorda quem estiver aguardando uma captura para (workflow_id, node_id)."""
    evt = _CAPTURE_EVENTS.get(_event_key(workflow_id, node_id))
    if evt is not None:
        evt.set()


async def wait_for_capture(
    workflow_id: UUID,
    node_id: str,
    timeout_seconds: float,
) -> bool:
    """Aguarda ate timeout_seconds por uma nova captura.

    Retorna True se o Event foi acionado, False em caso de timeout.
    O Event nao e consumido automaticamente aqui — ``clear_event`` e
    responsabilidade do chamador depois de obter a linha do banco.
    """
    evt = _get_or_create_event(workflow_id, node_id)
    evt.clear()
    try:
        await asyncio.wait_for(evt.wait(), timeout=timeout_seconds)
        return True
    except asyncio.TimeoutError:
        return False


def clear_event(workflow_id: UUID, node_id: str) -> None:
    """Remove a entrada do bus para liberar memoria."""
    _CAPTURE_EVENTS.pop(_event_key(workflow_id, node_id), None)


# ---------------------------------------------------------------------------
# Resolucao de path -> workflow + no webhook
# ---------------------------------------------------------------------------


def _node_webhook_config(node: dict[str, Any]) -> dict[str, Any] | None:
    """Extrai a config do no se for do tipo webhook; None caso contrario."""
    data = node.get("data") if isinstance(node, dict) else None
    if not isinstance(data, dict):
        return None
    node_type = str(node.get("type") or "")
    data_type = str(data.get("type") or "")
    if "webhook" not in (node_type, data_type):
        return None
    return data


def _extract_webhook_nodes(workflow: Workflow) -> list[tuple[str, dict[str, Any]]]:
    """Retorna lista de (node_id, config) para cada no webhook do workflow."""
    definition = workflow.definition if isinstance(workflow.definition, dict) else {}
    nodes = definition.get("nodes") or []
    result: list[tuple[str, dict[str, Any]]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        cfg = _node_webhook_config(node)
        if cfg is None:
            continue
        node_id = str(node.get("id") or "")
        if node_id:
            result.append((node_id, cfg))
    return result


def _normalize_path(raw: str) -> str:
    return raw.strip().strip("/")


_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


async def resolve_webhook(
    db: AsyncSession,
    raw_path: str,
) -> tuple[Workflow, str, dict[str, Any]] | None:
    """Resolve ``raw_path`` para (workflow, node_id, config do no).

    O path pode ser o UUID do workflow (selecionando o primeiro no
    webhook encontrado) ou o ``path`` custom configurado em um no
    webhook de qualquer workflow. Retorna None se nao resolver.
    """
    candidate = _normalize_path(raw_path)
    if not candidate:
        return None

    # 1) tenta como UUID
    if _UUID_PATTERN.match(candidate):
        try:
            workflow_id = UUID(candidate)
        except ValueError:
            workflow_id = None  # pragma: no cover
        if workflow_id is not None:
            result = await db.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                return None
            nodes = _extract_webhook_nodes(workflow)
            if not nodes:
                return None
            node_id, cfg = nodes[0]
            return workflow, node_id, cfg

    # 2) busca por path custom — varredura por Python.
    # Volume esperado e baixo (dezenas/centenas de workflows por workspace).
    # Caso cresca, indexar com GIN sobre o JSONB.
    stmt = select(Workflow)
    result = await db.execute(stmt)
    for workflow in result.scalars().all():
        for node_id, cfg in _extract_webhook_nodes(workflow):
            cfg_path = cfg.get("path")
            if isinstance(cfg_path, str) and _normalize_path(cfg_path) == candidate:
                return workflow, node_id, cfg
    return None


# ---------------------------------------------------------------------------
# Autenticacao
# ---------------------------------------------------------------------------


def _constant_time_equals(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def authenticate_webhook(
    request: Request,
    auth_config: dict[str, Any] | None,
) -> str | None:
    """Valida a autenticacao configurada no no.

    Retorna None em caso de sucesso, ou uma string com a razao da
    falha (o caller transforma em HTTP 401 com esse detail).
    """
    if not isinstance(auth_config, dict):
        return None
    auth_type = str(auth_config.get("type") or "none")
    if auth_type == "none":
        return None

    if auth_type == "header":
        expected_name = str(auth_config.get("header_name") or "").strip()
        expected_value = auth_config.get("header_value")
        if not expected_name or expected_value is None:
            return "Autenticacao por header mal configurada."
        received = request.headers.get(expected_name)
        if not _constant_time_equals(received, expected_value):
            return "Credencial invalida."
        return None

    if auth_type == "basic":
        expected_user = auth_config.get("username")
        expected_pass = auth_config.get("password")
        header = request.headers.get("authorization") or ""
        if not header.lower().startswith("basic "):
            return "Credencial invalida."
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
        except Exception:  # noqa: BLE001
            return "Credencial invalida."
        if ":" not in decoded:
            return "Credencial invalida."
        user, _, password = decoded.partition(":")
        if not _constant_time_equals(user, expected_user):
            return "Credencial invalida."
        if not _constant_time_equals(password, expected_pass):
            return "Credencial invalida."
        return None

    if auth_type == "jwt":
        secret = auth_config.get("jwt_secret")
        algorithm = str(auth_config.get("jwt_algorithm") or "HS256")
        if not secret:
            return "Autenticacao JWT mal configurada."
        header = request.headers.get("authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
        if not token:
            return "Token ausente."
        try:
            jwt.decode(token, secret, algorithms=[algorithm])
        except jwt.ExpiredSignatureError:
            return "Token expirado."
        except jwt.PyJWTError:
            return "Token invalido."
        return None

    return "Tipo de autenticacao desconhecido."


# ---------------------------------------------------------------------------
# Extracao de payload
# ---------------------------------------------------------------------------


async def extract_payload(
    request: Request,
    raw_body: bool,
) -> dict[str, Any]:
    """Monta a estrutura padronizada repassada ao processor do no webhook.

    Formato de saida:

    ``{"method": str, "headers": {..}, "query_params": {..},
       "body": <json-or-none>, "raw": "<base64>" | None}``
    """
    headers = {k: v for k, v in request.headers.items()}
    query_params = {k: v for k, v in request.query_params.items()}

    body: Any = None
    raw_b64: str | None = None

    if raw_body:
        raw_bytes = await request.body()
        raw_b64 = base64.b64encode(raw_bytes).decode("ascii")
    else:
        raw_bytes = await request.body()
        if raw_bytes:
            try:
                import json

                body = json.loads(raw_bytes.decode("utf-8"))
            except Exception:  # noqa: BLE001
                body = {"payload": raw_bytes.decode("utf-8", errors="replace")}

    return {
        "method": request.method,
        "headers": headers,
        "query_params": query_params,
        "body": body,
        "raw": raw_b64,
    }


# ---------------------------------------------------------------------------
# Persistencia das capturas de teste
# ---------------------------------------------------------------------------


async def upsert_test_capture(
    db: AsyncSession,
    workflow_id: UUID,
    node_id: str,
    *,
    method: str,
    headers: dict[str, str],
    query_params: dict[str, Any],
    body: Any,
    raw_b64: str | None,
) -> WebhookTestCapture:
    """Faz upsert de uma captura unica por (workflow_id, node_id)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=CAPTURE_TTL_MINUTES)

    stmt = pg_insert(WebhookTestCapture).values(
        workflow_id=workflow_id,
        node_id=node_id,
        method=method,
        headers=headers,
        query_params=query_params,
        body=body,
        raw_body_b64=raw_b64,
        captured_at=now,
        expires_at=expires_at,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_webhook_test_workflow_node",
        set_={
            "method": stmt.excluded.method,
            "headers": stmt.excluded.headers,
            "query_params": stmt.excluded.query_params,
            "body": stmt.excluded.body,
            "raw_body_b64": stmt.excluded.raw_body_b64,
            "captured_at": stmt.excluded.captured_at,
            "expires_at": stmt.excluded.expires_at,
        },
    ).returning(WebhookTestCapture)

    result = await db.execute(stmt)
    await db.commit()
    row = result.scalar_one()
    notify_capture(workflow_id, node_id)
    return row


async def fetch_latest_capture(
    db: AsyncSession,
    workflow_id: UUID,
    node_id: str,
    *,
    after: datetime | None = None,
) -> WebhookTestCapture | None:
    """Retorna a captura atual para (workflow_id, node_id), se existir.

    Quando ``after`` e informado, retorna apenas se ``captured_at`` for
    estritamente maior (util para "aguardar proxima").
    """
    stmt = select(WebhookTestCapture).where(
        WebhookTestCapture.workflow_id == workflow_id,
        WebhookTestCapture.node_id == node_id,
    )
    if after is not None:
        stmt = stmt.where(WebhookTestCapture.captured_at > after)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_captures(
    db: AsyncSession,
    workflow_id: UUID,
    node_id: str,
) -> int:
    """Remove capturas pendentes do par (workflow_id, node_id)."""
    result = await db.execute(
        delete(WebhookTestCapture).where(
            WebhookTestCapture.workflow_id == workflow_id,
            WebhookTestCapture.node_id == node_id,
        )
    )
    await db.commit()
    clear_event(workflow_id, node_id)
    return int(result.rowcount or 0)


async def purge_expired_captures(db: AsyncSession) -> int:
    """Remove capturas expiradas; invocada por task periodica."""
    result = await db.execute(
        delete(WebhookTestCapture).where(
            WebhookTestCapture.expires_at < datetime.now(timezone.utc)
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Montagem de URLs
# ---------------------------------------------------------------------------


def resolve_base_url(request: Request | None) -> str:
    """Retorna a base URL publica do backend.

    Prioridade: ``settings.EXTERNAL_BASE_URL`` > ``request.base_url``.
    """
    if settings.EXTERNAL_BASE_URL:
        return settings.EXTERNAL_BASE_URL.rstrip("/")
    if request is not None:
        return str(request.base_url).rstrip("/")
    return "http://localhost:8000"


def build_webhook_urls(
    request: Request | None,
    workflow: Workflow,
    node_cfg: dict[str, Any],
) -> tuple[str, str, str]:
    """Monta (path_exibido, test_url, production_url) para o no webhook."""
    base = resolve_base_url(request)
    custom = node_cfg.get("path") if isinstance(node_cfg, dict) else None
    path = _normalize_path(custom) if isinstance(custom, str) and custom.strip() else str(workflow.id)
    test_url = f"{base}/api/v1/webhook-test/{path}"
    prod_url = f"{base}/api/v1/webhook/{path}"
    return path, test_url, prod_url


# ---------------------------------------------------------------------------
# Resposta (on_finish)
# ---------------------------------------------------------------------------


def build_response_body(
    execution_result: Any,
    response_data: str,
) -> Any:
    """Constroi o body de resposta no modo ``on_finish`` a partir do
    resultado emitido pelo runner.

    Heuristica simples: busca a lista do ultimo no com chave "data" e
    serializa conforme ``response_data``.
    """
    if response_data == "no_body":
        return None

    rows: list[Any] | None = None

    if isinstance(execution_result, dict):
        last_output = execution_result.get("output")
        if isinstance(last_output, dict):
            data_field = last_output.get("data")
            if isinstance(data_field, list):
                rows = data_field

    if rows is None:
        return execution_result if isinstance(execution_result, dict) else {}

    if response_data == "first_entry_json":
        return rows[0] if rows else {}
    if response_data == "all_entries":
        return rows
    return rows
