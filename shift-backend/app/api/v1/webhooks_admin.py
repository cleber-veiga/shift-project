"""
Endpoints autenticados para apoio a UI do no Webhook:

- ``GET  /workflows/{workflow_id}/webhook/urls``: resolve test/production URLs
- ``POST /workflows/{workflow_id}/webhook/listen``: bloqueia ate receber
  uma captura de teste (usado pelo botao "Listen for test event")
- ``DELETE /workflows/{workflow_id}/webhook/listen``: limpa capturas
  pendentes (cancelamento pela UI)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from app.models.workflow import Workflow
from app.schemas.workflow import WebhookCaptureResponse, WebhookUrlsResponse
from app.services import webhook_service


router = APIRouter(prefix="/workflows", tags=["webhooks"])


# Janela para considerar uma captura existente "recente o suficiente" para
# ser devolvida imediatamente ao clicar em "Listen for test event" — UX
# espelha o n8n, que mostra a captura mais recente se o usuario acabou de
# fazer curl e voltou para a UI.
RECENT_CAPTURE_WINDOW = timedelta(minutes=5)


async def _load_workflow(db: AsyncSession, workflow_id: UUID) -> Workflow:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )
    return workflow


def _first_webhook_node(workflow: Workflow) -> tuple[str | None, dict]:
    definition = workflow.definition if isinstance(workflow.definition, dict) else {}
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        data_type = str(data.get("type") or "")
        if "webhook" in (node_type, data_type):
            return str(node.get("id") or ""), data
    return None, {}


@router.get(
    "/{workflow_id}/webhook/urls",
    response_model=WebhookUrlsResponse,
)
async def get_webhook_urls(
    workflow_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> WebhookUrlsResponse:
    """Retorna as URLs de test e producao do no webhook do workflow."""
    workflow = await _load_workflow(db, workflow_id)
    node_id, cfg = _first_webhook_node(workflow)
    path, test_url, prod_url = webhook_service.build_webhook_urls(
        request, workflow, cfg
    )
    production_ready = (
        str(workflow.status) == "published" and bool(workflow.is_published)
    )
    return WebhookUrlsResponse(
        node_id=node_id,
        http_method=str(cfg.get("http_method") or "POST"),
        path=path,
        test_url=test_url,
        production_url=prod_url,
        production_ready=production_ready,
    )


@router.post(
    "/{workflow_id}/webhook/listen",
    response_model=WebhookCaptureResponse,
)
async def listen_for_test_event(
    workflow_id: UUID,
    node_id: str = Query(..., description="ID do no webhook no React Flow."),
    timeout_seconds: int = Query(120, ge=5, le=600),
    fresh: bool = Query(
        False,
        description=(
            "Se true, ignora qualquer captura pre-existente e aguarda somente "
            "a proxima. Default false espelha o n8n: ao clicar 'Listen', se "
            "ja existe uma captura recente no buffer, ela e retornada "
            "imediatamente."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> WebhookCaptureResponse:
    """Bloqueia ate timeout_seconds aguardando uma captura para o par
    (workflow_id, node_id). Retorna 408 em caso de timeout."""
    await _load_workflow(db, workflow_id)

    existing = await webhook_service.fetch_latest_capture(db, workflow_id, node_id)

    # Comportamento default (fresh=False): se ja ha uma captura recente no
    # buffer, devolve imediatamente. Isto cobre o caso em que o usuario faz
    # curl primeiro e depois abre a UI.
    if not fresh and existing is not None:
        captured = existing.captured_at
        # Postgres retorna timezone-aware; SQLite (testes) pode retornar naive.
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        if captured >= datetime.now(timezone.utc) - RECENT_CAPTURE_WINDOW:
            return WebhookCaptureResponse.model_validate(existing)

    # Caso contrario: usamos o captured_at existente (se houver) como
    # baseline e so retornamos uma captura estritamente posterior.
    baseline_ts: datetime | None = existing.captured_at if existing is not None else None

    remaining = float(timeout_seconds)
    deadline = asyncio.get_event_loop().time() + remaining

    while True:
        fresh = await webhook_service.fetch_latest_capture(
            db, workflow_id, node_id, after=baseline_ts
        )
        if fresh is not None:
            return WebhookCaptureResponse.model_validate(fresh)

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="Nenhuma captura recebida dentro do tempo limite.",
            )

        # Aguarda notificacao ate no maximo 1s por iteracao (fallback se o
        # Event for disparado em outro processo — polling como rede de
        # protecao).
        wait_s = min(remaining, 1.0)
        await webhook_service.wait_for_capture(workflow_id, node_id, wait_s)


@router.delete(
    "/{workflow_id}/webhook/listen",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_test_captures(
    workflow_id: UUID,
    node_id: str = Query(..., description="ID do no webhook no React Flow."),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> None:
    """Remove as capturas pendentes para (workflow_id, node_id)."""
    await _load_workflow(db, workflow_id)
    await webhook_service.delete_captures(db, workflow_id, node_id)
