"""
Endpoints de execucao e acompanhamento de workflows.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from app.schemas.workflow import ExecutionResponse, ExecutionStatusResponse
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
    _=Depends(require_permission("workspace", "VIEWER")),
) -> ExecutionResponse:
    """Submete um workflow para execucao assincrona no Prefect."""
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
    _=Depends(require_permission("workspace", "VIEWER")),
) -> StreamingResponse:
    """Executa um workflow em modo de teste com streaming SSE por no.

    Retorna uma stream de eventos Server-Sent Events:
    - execution_start
    - node_start  / node_complete / node_error  (um par por no)
    - execution_complete
    - error (caso critico antes de comecar)
    """
    async def event_stream():
        async for chunk in workflow_test_service.run_streaming(workflow_id=workflow_id):
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
