"""
Endpoints de execucao e acompanhamento de workflows.
"""

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from sqlalchemy import select as sa_select

from app.models.workflow import WorkflowExecution, WorkflowNodeExecution
from app.schemas.workflow import (
    ExecutionDetailResponse,
    ExecutionResponse,
    ExecutionStatusResponse,
    NodeExecutionResponse,
)
from app.services import execution_registry
from app.services.workflow_service import workflow_service
from app.services.workflow_test_service import workflow_test_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post(
    "/{workflow_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_workflow(
    workflow_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> ExecutionResponse:
    """Submete um workflow para execucao assincrona em background."""
    try:
        input_data = await _extract_request_payload(request)
        return await workflow_service.execute_workflow(
            db=db,
            workflow_id=workflow_id,
            input_data=input_data,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{workflow_id}/test",
    status_code=status.HTTP_200_OK,
    response_class=StreamingResponse,
)
async def test_workflow(
    workflow_id: UUID,
    target_node_id: Optional[str] = Query(None, description="Se informado, executa somente ate este no (inclusive)."),
    mode: Optional[str] = Query(None, description="Override do modo: 'test' ou 'production'. Se omitido, usa o status do workflow (draft→test, published→production)."),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> StreamingResponse:
    """Executa um workflow com streaming SSE por no.

    O modo de execucao e derivado automaticamente do campo ``status`` do workflow:
    - draft   → test (extrai ate 200 linhas por no de entrada)
    - published → production (extrai todas as linhas, fluxo completo)

    O parametro ``mode`` pode ser usado como override explicito.

    Retorna uma stream de eventos Server-Sent Events:
    - execution_start (inclui campo 'mode')
    - node_start  / node_complete / node_error  (um par por no)
    - execution_complete
    - error (caso critico antes de comecar)
    """
    effective_mode = mode if mode in ("test", "production") else None

    async def event_stream():
        async for chunk in workflow_test_service.run_streaming(
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            mode=effective_mode,
        ):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/executions/running")
async def list_running_executions(
    _=Depends(require_permission("workspace", "VIEWER")),
) -> dict[str, list[str]]:
    """Retorna as execucoes atualmente ativas neste processo."""
    return {
        "execution_ids": [str(eid) for eid in execution_registry.list_running()],
    }


@router.get(
    "/executions/{execution_id}/status",
    response_model=ExecutionStatusResponse,
)
async def get_execution_status(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> ExecutionStatusResponse:
    """Consulta o status de uma execucao de workflow."""
    result = await workflow_service.get_execution_status(db, execution_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )
    return result


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: UUID,
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, str]:
    """
    Cancela uma execucao em andamento.

    Aciona ``task.cancel()`` na coroutine registrada; o finalizador do
    ``WorkflowExecutionService`` marca ``status=CANCELLED`` no banco.
    Retorna 404 se a execucao nao esta ativa (nunca registrada, ja
    finalizada, ou rodando em outro processo).
    """
    cancelled = await execution_registry.cancel(execution_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execucao nao encontrada ou ja finalizada.",
        )
    return {"status": "CANCELLED"}


@router.get(
    "/executions/{execution_id}/details",
    response_model=ExecutionDetailResponse,
)
async def get_execution_details(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> ExecutionDetailResponse:
    """Retorna detalhes de uma execucao incluindo o historico de cada no."""
    result = await db.execute(
        sa_select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )

    nodes_result = await db.execute(
        sa_select(WorkflowNodeExecution)
        .where(WorkflowNodeExecution.execution_id == execution_id)
        .order_by(WorkflowNodeExecution.started_at.asc())
    )
    node_rows = list(nodes_result.scalars().all())

    return ExecutionDetailResponse(
        execution_id=execution.id,
        status=execution.status,
        result=execution.result,
        error_message=execution.error_message,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        nodes=[NodeExecutionResponse.model_validate(n) for n in node_rows],
    )


async def _extract_request_payload(request: Request) -> dict[str, Any]:
    if not request.headers.get("content-type", "").startswith("application/json"):
        return {}

    try:
        payload = await request.json()
    except Exception:
        return {}

    if isinstance(payload, dict):
        return payload

    return {"payload": payload}
