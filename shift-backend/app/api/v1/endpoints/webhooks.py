"""
Endpoint de webhook para disparo externo de workflows.

Sistemas externos enviam POST /api/v1/webhooks/{workflow_id} com
um payload JSON. O workflow e despachado imediatamente em background,
sem aguardar a conclusao do fluxo.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.models.workflow import Workflow
from app.schemas.workflow import ExecutionResponse
from app.services.workflow_service import workflow_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/{workflow_id}",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_webhook(
    workflow_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ExecutionResponse:
    """
    Recebe um webhook externo e cria uma execucao assincrona do workflow.

    A validacao verifica se o workflow existe, se esta ativo e se o grafo
    possui ao menos um no de trigger do tipo webhook.
    """
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    # O model atual nao expoe is_active. Este bloco ja deixa o endpoint
    # pronto para usar o campo assim que ele for adicionado ao model/schema.
    if hasattr(workflow, "is_active") and not bool(getattr(workflow, "is_active")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow inativo para recebimento de webhooks.",
        )

    definition = workflow.definition if isinstance(workflow.definition, dict) else {}
    nodes = definition.get("nodes", [])
    has_webhook_node = any(
        _extract_trigger_type(node) == "webhook"
        for node in nodes
        if isinstance(node, dict)
    )

    if not has_webhook_node:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este workflow nao possui um no de trigger do tipo webhook.",
        )

    payload = await _extract_payload(request)

    try:
        return await workflow_service.run(
            db=db,
            workflow_id=workflow_id,
            triggered_by="webhook",
            input_data=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


async def _extract_payload(request: Request) -> dict[str, Any]:
    """Le o body JSON sem falhar quando o integrador enviar payload vazio."""
    try:
        payload = await request.json()
    except Exception:
        return {}

    if isinstance(payload, dict):
        return payload

    return {"payload": payload}


def _extract_trigger_type(node: dict[str, Any]) -> str | None:
    """Extrai o tipo de trigger suportando schema novo e legado."""
    node_type = str(node.get("type", ""))
    data = node.get("data", {})
    data_type = str(data.get("type", ""))

    if node_type in {"manual", "webhook", "cron", "polling"}:
        return node_type

    if data_type in {"manual", "webhook", "cron", "polling"}:
        return data_type

    if node_type == "triggerNode" or data_type == "triggerNode":
        legacy_type = str(data.get("trigger_type", ""))
        return "cron" if legacy_type == "schedule" else legacy_type

    return None
