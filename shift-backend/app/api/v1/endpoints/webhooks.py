"""
Rotas publicas de recepcao de webhooks.

Expoe dois prefixos:

- ``/api/v1/webhook/{path:path}`` — recebe requisicoes externas de
  producao. Dispara o workflow via ``workflow_service.run``. A URL so
  funciona quando o workflow esta publicado (status=published AND
  is_published=True).
- ``/api/v1/webhook-test/{path:path}`` — rota de "escuta" usada pelo
  botao "Listen for test event" do editor. NAO dispara o workflow —
  apenas faz upsert em ``webhook_test_captures`` e acorda a UI.

Alem disso, mantem compatibilidade com a rota legada
``POST /api/v1/webhooks/{workflow_id}`` (sem auth, respond_mode
immediately, POST/none) para nao quebrar integracoes que ainda
apontam para ela.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.logging import get_logger
from app.models.workflow import Workflow
from app.schemas.workflow import ExecutionResponse
from app.services import webhook_service
from app.services.workflow_service import workflow_service


logger = get_logger(__name__)
router = APIRouter(tags=["webhooks"])


_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_ON_FINISH_TIMEOUT_SECONDS = 60.0
_USING_RESPOND_NODE_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_production_ready(workflow: Workflow) -> bool:
    return str(workflow.status) == "published" and bool(workflow.is_published)


def _method_matches(cfg: dict[str, Any], request_method: str) -> bool:
    configured = str(cfg.get("http_method") or "POST").upper()
    return configured == request_method.upper()


def _apply_response_headers(
    response: Response,
    cfg: dict[str, Any],
    request: Request,
) -> None:
    headers = cfg.get("response_headers")
    if isinstance(headers, dict):
        for k, v in headers.items():
            response.headers[str(k)] = str(v)

    origins = cfg.get("allowed_origins")
    if isinstance(origins, str) and origins.strip():
        origin = request.headers.get("origin")
        if origins.strip() == "*" or (origin and origin in _parse_origins(origins)):
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
            response.headers["Vary"] = "Origin"


def _parse_origins(csv: str) -> set[str]:
    return {o.strip() for o in csv.split(",") if o.strip()}


def _build_preflight_response(request: Request, cfg: dict[str, Any]) -> Response:
    """Monta a resposta de CORS preflight (OPTIONS).

    Se ``allowed_origins`` nao estiver configurado, retorna 204 sem
    cabecalhos CORS — o navegador bloqueia sozinho, comportamento
    previsivel e identico a uma rota inexistente.
    """
    resp = Response(status_code=204)
    origins = cfg.get("allowed_origins")
    if not isinstance(origins, str) or not origins.strip():
        return resp

    origin = request.headers.get("origin")
    allowed = origins.strip() == "*" or (
        origin is not None and origin in _parse_origins(origins)
    )
    if not allowed:
        return resp

    resp.headers["Access-Control-Allow-Origin"] = origin or "*"
    resp.headers["Access-Control-Allow-Methods"] = ",".join(
        m for m in _ALLOWED_METHODS if m != "OPTIONS"
    )
    resp.headers["Access-Control-Allow-Headers"] = (
        request.headers.get("access-control-request-headers")
        or "Content-Type,Authorization,X-Api-Key"
    )
    resp.headers["Access-Control-Max-Age"] = "600"
    resp.headers["Vary"] = "Origin"
    return resp


# ---------------------------------------------------------------------------
# Rota de producao: /api/v1/webhook/{path}
# ---------------------------------------------------------------------------


@router.api_route("/webhook/{path:path}", methods=_ALLOWED_METHODS)
async def receive_production_webhook(
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Recebe um webhook externo de producao e dispara o workflow."""
    resolved = await webhook_service.resolve_webhook(db, path)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nao encontrado.")
    workflow, node_id, cfg = resolved

    # OPTIONS (CORS preflight) e tratado antes do gate de producao: um
    # preflight nao pode falhar so porque o workflow esta em draft, senao
    # o proprio CORS quebra antes do usuario publicar.
    if request.method == "OPTIONS":
        return _build_preflight_response(request, cfg)

    if not _is_production_ready(workflow):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nao encontrado.")

    if not _method_matches(cfg, request.method):
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="Metodo HTTP nao permitido para este webhook.",
        )

    auth_error = webhook_service.authenticate_webhook(request, cfg.get("authentication"))
    if auth_error is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=auth_error)

    payload = await webhook_service.extract_payload(
        request,
        raw_body=bool(cfg.get("raw_body")),
    )

    respond_mode = str(cfg.get("respond_mode") or "immediately")
    response_code = int(cfg.get("response_code") or 200)
    response_data = str(cfg.get("response_data") or "first_entry_json")

    if respond_mode == "using_respond_node":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="respond_to_webhook node nao implementado (TODO).",
        )

    if respond_mode == "immediately":
        try:
            await workflow_service.run(
                db=db,
                workflow_id=workflow.id,
                triggered_by="webhook",
                input_data=payload,
                wait=False,
                mode="production",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        body_content = b"" if response_data == "no_body" else b"{}"
        resp = Response(content=body_content, status_code=response_code, media_type="application/json")
        _apply_response_headers(resp, cfg, request)
        return resp

    # respond_mode == "on_finish": aguarda execucao concluir.
    try:
        execution_result_box: dict[str, Any] = {}

        async def _sink(event: dict[str, Any]) -> None:
            if event.get("type") == "execution_complete":
                execution_result_box["result"] = event

        await asyncio.wait_for(
            workflow_service.run(
                db=db,
                workflow_id=workflow.id,
                triggered_by="webhook",
                input_data=payload,
                wait=True,
                mode="production",
                event_sink=_sink,
            ),
            timeout=_ON_FINISH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Workflow nao concluiu a tempo.",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    body = webhook_service.build_response_body(
        execution_result_box.get("result"),
        response_data,
    )

    if response_data == "no_body" or body is None:
        resp = Response(status_code=response_code)
    else:
        resp = JSONResponse(content=body, status_code=response_code)
    _apply_response_headers(resp, cfg, request)
    _ = node_id  # node_id e exposto ao runner via input_data; nao precisa aqui
    return resp


# ---------------------------------------------------------------------------
# Rota de teste: /api/v1/webhook-test/{path}
# ---------------------------------------------------------------------------


@router.api_route("/webhook-test/{path:path}", methods=_ALLOWED_METHODS)
async def receive_test_webhook(
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Rota de escuta — nao dispara workflow, apenas registra a captura."""
    resolved = await webhook_service.resolve_webhook(db, path)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nao encontrado.")
    workflow, node_id, cfg = resolved

    if request.method == "OPTIONS":
        return _build_preflight_response(request, cfg)

    payload = await webhook_service.extract_payload(
        request,
        raw_body=bool(cfg.get("raw_body")),
    )

    await webhook_service.upsert_test_capture(
        db,
        workflow.id,
        node_id,
        method=payload["method"],
        headers=payload["headers"],
        query_params=payload["query_params"],
        body=payload["body"],
        raw_b64=payload.get("raw"),
    )

    resp = JSONResponse({"status": "captured"}, status_code=status.HTTP_200_OK)
    _apply_response_headers(resp, cfg, request)
    return resp


# ---------------------------------------------------------------------------
# Compatibilidade: POST /api/v1/webhooks/{workflow_id}
# ---------------------------------------------------------------------------


@router.post(
    "/webhooks/{workflow_id}",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
    summary="(deprecated) Dispara webhook via UUID do workflow",
    description=(
        "Rota de compatibilidade com integracoes anteriores ao no Webhook "
        "estilo n8n. Prefira ``POST /api/v1/webhook/{path}`` (com "
        "autenticacao, method matching e respond modes)."
    ),
)
async def receive_legacy_webhook(
    workflow_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ExecutionResponse:
    """Mantem integracoes antigas — POST sem auth, respond immediately."""
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    definition = workflow.definition if isinstance(workflow.definition, dict) else {}
    nodes = definition.get("nodes") or []
    has_webhook_node = any(
        _extract_trigger_type(n) == "webhook" for n in nodes if isinstance(n, dict)
    )
    if not has_webhook_node:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este workflow nao possui um no de trigger do tipo webhook.",
        )

    payload = await webhook_service.extract_payload(request, raw_body=False)

    try:
        return await workflow_service.run(
            db=db,
            workflow_id=workflow_id,
            triggered_by="webhook",
            input_data=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _extract_trigger_type(node: dict[str, Any]) -> str | None:
    node_type = str(node.get("type", ""))
    data = node.get("data", {}) if isinstance(node.get("data"), dict) else {}
    data_type = str(data.get("type", ""))

    if node_type in {"manual", "webhook", "cron", "polling"}:
        return node_type
    if data_type in {"manual", "webhook", "cron", "polling"}:
        return data_type
    if node_type == "triggerNode" or data_type == "triggerNode":
        legacy_type = str(data.get("trigger_type", ""))
        return "cron" if legacy_type == "schedule" else legacy_type
    return None
