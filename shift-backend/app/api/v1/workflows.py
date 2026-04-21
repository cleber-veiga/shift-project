"""
Endpoints de execucao e acompanhamento de workflows.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from sqlalchemy import func as sa_func, select as sa_select

from app.models.workflow import WorkflowExecution, WorkflowNodeExecution
from app.schemas.workflow import (
    ExecuteWorkflowRequest,
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionResponse,
    ExecutionStatusResponse,
    ExecutionSummaryResponse,
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
    payload: ExecuteWorkflowRequest = Body(default_factory=ExecuteWorkflowRequest),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> ExecutionResponse:
    """Submete um workflow para execucao assincrona em background.

    O corpo e opcional; quando omitido o workflow roda sem variaveis externas.
    ``variable_values`` mapeia nome da variavel ao valor fornecido pelo
    chamador — obrigatorias sem valor retornam HTTP 400.
    """
    try:
        return await workflow_service.execute_workflow(
            db=db,
            workflow_id=workflow_id,
            input_data={"variable_values": payload.variable_values},
        )
    except ValueError as exc:
        detail = str(exc)
        http_status = (
            status.HTTP_400_BAD_REQUEST
            if "obrigatoria" in detail or "deve ser" in detail
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=http_status, detail=detail) from exc


@router.post(
    "/{workflow_id}/test",
    status_code=status.HTTP_200_OK,
    response_class=StreamingResponse,
)
async def test_workflow(
    workflow_id: UUID,
    request: Request,
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

    # Body opcional: ``{"input_data": {...}}`` permite simular a chamada
    # deste workflow como sub-workflow (alimenta o no workflow_input).
    input_data: dict[str, Any] | None = None
    if request.headers.get("content-length") not in (None, "", "0"):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = None
        if isinstance(body, dict):
            raw = body.get("input_data")
            if isinstance(raw, dict):
                input_data = raw

    async def event_stream():
        async for chunk in workflow_test_service.run_streaming(
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            mode=effective_mode,
            input_data=input_data,
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
        triggered_by=execution.triggered_by,
        input_data=execution.input_data,
        result=execution.result,
        error_message=execution.error_message,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        nodes=[NodeExecutionResponse.model_validate(n) for n in node_rows],
    )


@router.get(
    "/{workflow_id}/executions",
    response_model=ExecutionListResponse,
)
async def list_workflow_executions(
    workflow_id: UUID,
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filtra por status: PENDING, RUNNING, SUCCESS/COMPLETED, FAILED, CANCELLED, ABORTED, CRASHED.",
    ),
    triggered_by: Optional[str] = Query(
        None,
        description="Filtra por origem: manual, cron, api, webhook.",
    ),
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> ExecutionListResponse:
    """Lista execucoes de um workflow com filtros e paginacao.

    Usado pela aba "Executions" do editor de workflows. Retorna uma
    linha enxuta por execucao, ja com ``duration_ms`` calculado e
    ``node_count`` agregado em uma unica query.
    """
    # Frontend trabalha com SUCCESS; no banco usamos COMPLETED. Aceitamos
    # ambos sem forcar o cliente a saber dessa diferenca historica.
    status_clause: list[Any] = []
    if status_filter:
        upper = status_filter.upper()
        if upper == "SUCCESS":
            status_clause = [WorkflowExecution.status == "COMPLETED"]
        else:
            status_clause = [WorkflowExecution.status == upper]

    filters: list[Any] = [WorkflowExecution.workflow_id == workflow_id]
    if status_clause:
        filters.extend(status_clause)
    if triggered_by:
        filters.append(WorkflowExecution.triggered_by == triggered_by.lower())
    if date_from is not None:
        filters.append(WorkflowExecution.started_at >= date_from)
    if date_to is not None:
        filters.append(WorkflowExecution.started_at <= date_to)

    node_count_sq = (
        sa_select(
            WorkflowNodeExecution.execution_id.label("exec_id"),
            sa_func.count(WorkflowNodeExecution.id).label("node_count"),
        )
        .group_by(WorkflowNodeExecution.execution_id)
        .subquery()
    )

    stmt = (
        sa_select(
            WorkflowExecution.id,
            WorkflowExecution.workflow_id,
            WorkflowExecution.status,
            WorkflowExecution.triggered_by,
            WorkflowExecution.started_at,
            WorkflowExecution.completed_at,
            WorkflowExecution.error_message,
            sa_func.coalesce(node_count_sq.c.node_count, 0).label("node_count"),
        )
        .select_from(
            WorkflowExecution.__table__.outerjoin(
                node_count_sq,
                node_count_sq.c.exec_id == WorkflowExecution.id,
            )
        )
        .where(*filters)
        .order_by(
            WorkflowExecution.started_at.desc().nulls_last(),
            WorkflowExecution.id.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
    )

    result = await db.execute(stmt)
    rows = result.mappings().all()

    count_stmt = sa_select(sa_func.count()).select_from(WorkflowExecution).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    items: list[ExecutionSummaryResponse] = []
    for row in rows:
        duration_ms: int | None = None
        if row["started_at"] is not None and row["completed_at"] is not None:
            delta = row["completed_at"] - row["started_at"]
            duration_ms = int(delta.total_seconds() * 1000)
        items.append(
            ExecutionSummaryResponse(
                id=row["id"],
                workflow_id=row["workflow_id"],
                status=row["status"],
                triggered_by=row["triggered_by"],
                duration_ms=duration_ms,
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                node_count=int(row["node_count"] or 0),
                error_message=row["error_message"],
            )
        )

    return ExecutionListResponse(items=items, total=int(total), page=page, size=size)


@router.delete(
    "/executions/{execution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> None:
    """Remove uma execucao do historico.

    Nao permite remover execucoes em andamento (``RUNNING``) — cancele
    primeiro via ``POST /executions/{id}/cancel``. As linhas associadas
    em ``workflow_node_executions`` sao removidas pelo cascade ORM.
    """
    result = await db.execute(
        sa_select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )
    if execution.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Execucao em andamento; cancele antes de excluir.",
        )

    await db.delete(execution)
    await db.commit()

