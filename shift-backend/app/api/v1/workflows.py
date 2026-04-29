"""
Endpoints de execucao e acompanhamento de workflows.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, populate_rate_limit_context
from app.core.config import settings
from app.core.rate_limit import limiter, _project_key_func, _user_key_func
from app.core.security import get_current_user as _resolve_user, require_permission
from sqlalchemy import func as sa_func, select as sa_select

from app.models.workflow import Workflow, WorkflowExecution, WorkflowExecutionLog, WorkflowNodeExecution
from app.models.workflow import WorkflowCheckpoint
from app.schemas.workflow import (
    CheckpointSummary,
    CheckpointsResponse,
    ExecuteWorkflowRequest,
    ExecutionDefinitionResponse,
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionLogEntry,
    ExecutionLogsResponse,
    ExecutionResponse,
    ExecutionSnapshotResponse,
    ExecutionStatusResponse,
    ExecutionSummaryResponse,
    NodeExecutionResponse,
    ReplayExecutionRequest,
    ReplayExecutionResponse,
    ValidateExecutionResponse,
)
from app.orchestration.flows.dynamic_runner import ConcurrencyLimitError, get_concurrency_metrics
from app.services import checkpoint_service, execution_registry
from app.services.workflow_service import workflow_service
from app.services.workflow_test_service import workflow_test_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post(
    "/{workflow_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(f"{settings.RATE_LIMIT_EXECUTE_USER_MINUTE}/minute", key_func=_user_key_func)
@limiter.limit(f"{settings.RATE_LIMIT_EXECUTE_USER_HOUR}/hour", key_func=_user_key_func)
@limiter.limit(f"{settings.RATE_LIMIT_EXECUTE_PROJECT_MINUTE}/minute", key_func=_project_key_func)
@limiter.limit(f"{settings.RATE_LIMIT_EXECUTE_PROJECT_HOUR}/hour", key_func=_project_key_func)
async def execute_workflow(
    request: Request,
    workflow_id: UUID,
    payload: ExecuteWorkflowRequest = Body(default_factory=ExecuteWorkflowRequest),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
    _rl=Depends(populate_rate_limit_context),
):
    """Submete um workflow para execucao assincrona em background.

    O corpo e opcional; quando omitido o workflow roda sem variaveis externas.
    ``variable_values`` mapeia nome da variavel ao valor fornecido pelo
    chamador — obrigatorias sem valor retornam HTTP 400.

    ``run_mode`` controla o escopo da execucao:
    - ``full``: execucao completa (padrao).
    - ``preview``: limita cada no de extracao a ``WORKFLOW_PREVIEW_MAX_ROWS``
      linhas — dry-run para validar transformacoes sem mover o volume real.
    - ``validate``: valida variaveis + testa conectividade e retorna
      sincronamente ``ValidateExecutionResponse`` (status 200). Nao cria
      ``WorkflowExecution`` e nao invoca o runner.
    """
    try:
        if payload.run_mode == "validate":
            result = await workflow_service.validate_workflow(
                db=db,
                workflow_id=workflow_id,
                input_data={"variable_values": payload.variable_values},
            )
            # validate e sincrono — devolvemos 200 em vez de 202.
            return result

        return await workflow_service.execute_workflow(
            db=db,
            workflow_id=workflow_id,
            input_data={"variable_values": payload.variable_values},
            retry_from_execution_id=payload.retry_from_execution_id,
            run_mode=payload.run_mode,
        )
    except ConcurrencyLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "30"},
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        if "escopo autorizado" in detail:
            # Conexao referenciada pertence a outro projeto/workspace — acesso negado.
            http_status = status.HTTP_403_FORBIDDEN
        elif "obrigatoria" in detail or "deve ser" in detail:
            http_status = status.HTTP_400_BAD_REQUEST
        else:
            http_status = status.HTTP_404_NOT_FOUND
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


@router.get("/concurrency")
async def get_execution_concurrency(
    _=Depends(require_permission("workspace", "VIEWER")),
) -> dict:
    """Retorna metricas de concorrencia de execucoes nesta instancia.

    Campos:
    - ``active_executions``: execucoes rodando agora.
    - ``queued_executions``: requests aguardando slot (em fila).
    - ``max_concurrent``: limite global (env SHIFT_MAX_CONCURRENT_EXECUTIONS).
    - ``max_per_project``: limite por projeto (env SHIFT_MAX_CONCURRENT_PER_PROJECT).
    - ``active_by_project``: mapa project_id -> contagem ativa.
    """
    return get_concurrency_metrics()


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
            WorkflowExecution.template_version,
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
                template_version=row["template_version"],
            )
        )

    return ExecutionListResponse(items=items, total=int(total), page=page, size=size)


async def _execution_or_404(
    db: AsyncSession,
    execution_id: UUID,
    current_user: Any,
    *,
    required_role: str = "VIEWER",
) -> WorkflowExecution:
    """Carrega a execution e valida acesso do usuario, mascarando cross-workspace
    como 404.

    Em SaaS multi-tenant, retornar 403 vaza a existencia do recurso para
    usuarios de outro workspace ("este id existe mas voce nao pode ver").
    Esta funcao retorna 404 nos dois casos (nao existe / nao acessivel)
    para nao expor informacao a quem nao tem direito.
    """
    from sqlalchemy import func as _sa_func
    from app.core.security import authorization_service
    from app.models.project import Project as _Project

    result = await db.execute(
        sa_select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )

    # Resolve workspace da execucao (via project ou direto). Mesma logica do
    # ``_resolve_workspace_id`` do authorization_service, replicada aqui para
    # poder mascarar 403 -> 404 sem fork em ``require_permission``.
    ws_q = (
        sa_select(
            _sa_func.coalesce(Workflow.workspace_id, _Project.workspace_id)
        )
        .select_from(Workflow)
        .outerjoin(_Project, _Project.id == Workflow.project_id)
        .where(Workflow.id == execution.workflow_id)
    )
    workspace_id = (await db.execute(ws_q)).scalar_one_or_none()
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )

    has_access = await authorization_service.has_permission(
        db=db,
        user_id=current_user.id,
        scope="workspace",
        required_role=required_role,
        scope_id=workspace_id,
    )
    if not has_access:
        # NAO retornar 403 — vazaria existencia do execution_id.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )
    return execution


async def _load_execution_with_snapshot(
    db: AsyncSession,
    execution: WorkflowExecution,
) -> tuple[WorkflowExecution, str | None, bool]:
    """Computa current_hash + diverged a partir de uma execucao ja autorizada."""
    wf_result = await db.execute(
        sa_select(Workflow.definition).where(Workflow.id == execution.workflow_id)
    )
    current_definition = wf_result.scalar_one_or_none()
    current_hash: str | None = None
    if current_definition is not None:
        current_hash = hashlib.sha256(
            json.dumps(current_definition, sort_keys=True, default=str).encode()
        ).hexdigest()

    diverged = (
        execution.template_version is not None
        and current_hash is not None
        and execution.template_version != current_hash
    )
    return execution, current_hash, diverged


@router.get(
    "/executions/{execution_id}/definition",
    response_model=ExecutionDefinitionResponse,
    summary="(Deprecado) Snapshot da definicao no contrato Sprint 4.1",
    description=(
        "Mantido para retro-compat com clientes que dependem dos campos "
        "``snapshot`` / ``snapshot_hash`` / ``current_hash`` / "
        "``definition_diverged``. Novos clientes devem usar "
        "``GET /executions/{id}/snapshot``."
    ),
)
async def get_execution_definition(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("workspace", "VIEWER")),
) -> ExecutionDefinitionResponse:
    execution = await _execution_or_404(db, execution_id, current_user)
    execution, current_hash, diverged = await _load_execution_with_snapshot(
        db, execution
    )
    return ExecutionDefinitionResponse(
        execution_id=execution.id,
        workflow_id=execution.workflow_id,
        snapshot=execution.template_snapshot,
        snapshot_hash=execution.template_version,
        current_hash=current_hash,
        definition_diverged=diverged,
    )


@router.get(
    "/executions/{execution_id}/snapshot",
    response_model=ExecutionSnapshotResponse,
    summary="Snapshot imutavel da execucao (audit trail)",
    description=(
        "Devolve a definicao do workflow exatamente como foi executada — "
        "ja renderizada (pos-Jinja2) com valores de variaveis declaradas "
        "como ``secret`` substituidos por ``<REDACTED>``. Nunca contem "
        "segredos em texto claro.\n\n"
        "Acesso restrito a membros do workspace que executou o workflow. "
        "Execucoes de outros workspaces retornam 404 (nao 403) para nao "
        "vazar a existencia do recurso."
    ),
    responses={
        200: {"description": "Snapshot retornado com hash atual para comparacao."},
        404: {"description": "Execucao nao existe ou nao e acessivel pelo usuario."},
    },
)
async def get_execution_snapshot(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_resolve_user),
) -> ExecutionSnapshotResponse:
    execution = await _execution_or_404(db, execution_id, current_user)
    execution, current_hash, diverged = await _load_execution_with_snapshot(
        db, execution
    )
    return ExecutionSnapshotResponse(
        execution_id=execution.id,
        workflow_id=execution.workflow_id,
        template_snapshot=execution.template_snapshot,
        template_version=execution.template_version,
        rendered_at=execution.rendered_at,
        current_template_version=current_hash,
        diverged=diverged,
    )


@router.post(
    "/executions/{execution_id}/replay",
    response_model=ReplayExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Replay deterministico de uma execucao",
    description=(
        "Cria uma NOVA execucao reusando o ``template_snapshot`` exato da "
        "execucao alvo — nao re-renderiza a definicao atual do workflow. "
        "Util para reproduzir resultados de auditoria mesmo apos edicoes "
        "posteriores no template.\n\n"
        "Acesso restrito a usuarios com role ``CONSULTANT`` no workspace. "
        "404 para usuarios de outro workspace (nao vazar existencia)."
    ),
    responses={
        201: {"description": "Nova execucao criada e enfileirada."},
        404: {"description": "Execucao original nao existe ou nao e acessivel."},
        409: {
            "description": (
                "``template_snapshot`` da execucao original esta ausente "
                "ou corrompido — replay impossivel."
            )
        },
        429: {"description": "Rate limit / cota de execucoes esgotada."},
    },
)
async def replay_execution(
    execution_id: UUID,
    payload: ReplayExecutionRequest = Body(default_factory=ReplayExecutionRequest),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_resolve_user),
) -> ReplayExecutionResponse:
    # Valida acesso primeiro: usuario sem role no workspace recebe 404.
    await _execution_or_404(db, execution_id, current_user, required_role="CONSULTANT")
    try:
        result = await workflow_service.replay_execution(
            db=db,
            execution_id=execution_id,
            triggered_by=payload.trigger_type,
        )
    except ConcurrencyLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "30"},
        ) from exc
    except ValueError as exc:
        # ValueErrors do replay_execution: snapshot ausente/corrompido.
        # Distinguimos workflow inexistente (404) do snapshot quebrado (409).
        msg = str(exc).lower()
        if (
            "snapshot" in msg
            or "utilizavel" in msg
            or "corrompido" in msg
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    latest = (
        await db.execute(
            sa_select(WorkflowExecution.template_version).where(
                WorkflowExecution.id == result.execution_id
            )
        )
    ).scalar_one_or_none()

    return ReplayExecutionResponse(
        execution_id=result.execution_id,
        original_execution_id=execution_id,
        status=result.status,
        template_version=latest,
    )


@router.get(
    "/executions/{execution_id}/logs",
    response_model=ExecutionLogsResponse,
)
async def get_execution_logs(
    execution_id: UUID,
    level: Optional[str] = Query(
        None,
        description="Filtra por nivel: info | warning | error.",
    ),
    node_id: Optional[str] = Query(
        None,
        description="Filtra logs de um no especifico.",
    ),
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> ExecutionLogsResponse:
    """Retorna o log estruturado de uma execucao para troubleshooting.

    Uma execucao pode gerar centenas de logs (um por evento do runner).
    O parametro ``limit`` (default 1000, max 5000) protege contra payloads
    enormes; ``truncated=true`` indica que ha mais entradas alem do retornado.

    Para download completo em formato texto, use
    ``GET /executions/{id}/logs/download``.
    """
    filters: list[Any] = [WorkflowExecutionLog.execution_id == execution_id]
    if level:
        level_lower = level.lower()
        if level_lower in ("info", "warning", "error"):
            filters.append(WorkflowExecutionLog.level == level_lower)
    if node_id:
        filters.append(WorkflowExecutionLog.node_id == node_id)

    count_stmt = sa_select(sa_func.count()).select_from(WorkflowExecutionLog).where(*filters)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    stmt = (
        sa_select(WorkflowExecutionLog)
        .where(*filters)
        .order_by(WorkflowExecutionLog.timestamp.asc(), WorkflowExecutionLog.id.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    return ExecutionLogsResponse(
        execution_id=execution_id,
        entries=[ExecutionLogEntry.model_validate(r) for r in rows],
        total=total,
        truncated=total > len(rows),
    )


@router.get("/executions/{execution_id}/logs/download")
async def download_execution_logs(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> StreamingResponse:
    """Baixa o log completo da execucao em texto plano (uma linha por evento).

    Nao pagina — stream direto do banco para o cliente. Usado pelo frontend
    no botao "Baixar log" e por ferramentas CLI de diagnostico.
    """
    # Verifica que a execucao existe (e que o usuario tem acesso via
    # permission dependency acima, que valida workspace).
    exists_stmt = sa_select(WorkflowExecution.id).where(WorkflowExecution.id == execution_id)
    if (await db.execute(exists_stmt)).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execucao '{execution_id}' nao encontrada.",
        )

    async def _text_stream():
        yield f"# Log de execucao {execution_id}\n"
        yield f"# Formato: TIMESTAMP  LEVEL  [NODE_ID]  MESSAGE\n\n"

        offset = 0
        page_size = 500
        while True:
            page_stmt = (
                sa_select(WorkflowExecutionLog)
                .where(WorkflowExecutionLog.execution_id == execution_id)
                .order_by(WorkflowExecutionLog.timestamp.asc(), WorkflowExecutionLog.id.asc())
                .offset(offset)
                .limit(page_size)
            )
            result = await db.execute(page_stmt)
            batch = list(result.scalars().all())
            if not batch:
                break
            for entry in batch:
                ts = entry.timestamp.isoformat() if entry.timestamp else "-"
                node_ref = f"[{entry.node_id}]" if entry.node_id else "[-]"
                yield f"{ts}  {entry.level.upper():<7}  {node_ref}  {entry.message}\n"
            if len(batch) < page_size:
                break
            offset += page_size

    return StreamingResponse(
        _text_stream(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="execution-{execution_id}.log"',
        },
    )


@router.get(
    "/executions/{execution_id}/checkpoints",
    response_model=CheckpointsResponse,
)
async def get_execution_checkpoints(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> CheckpointsResponse:
    """Lista checkpoints disponiveis para retomada de execucao falhada.

    Retorna os nos que completaram com sucesso e foram checkpointed,
    junto com o flag ``resumable`` que indica se ha ao menos um checkpoint
    valido (nao expirado, arquivo DuckDB presente).
    """
    from datetime import datetime, timezone

    result = await db.execute(
        sa_select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.source_execution_id == execution_id
        )
    )
    records = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    valid_nodes = await checkpoint_service.load_checkpoints(execution_id)

    checkpoints = [
        CheckpointSummary(
            node_id=r.node_id,
            created_at=r.created_at,
            expires_at=r.expires_at,
            used_by_execution_id=r.used_by_execution_id,
        )
        for r in records
    ]
    return CheckpointsResponse(
        source_execution_id=execution_id,
        checkpoints=checkpoints,
        resumable=bool(valid_nodes),
    )


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


# ─── Predicted Schema ──────────────────────────────────────────────────────────


@router.get("/{workflow_id}/nodes/{node_id}/predicted-schema")
async def get_predicted_schema(
    workflow_id: UUID,
    node_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Retorna o schema de saída previsto para um nó sem executar o workflow.

    Útil para que o frontend exiba colunas disponíveis em dropdowns de
    config (filter, mapper, join) e valide se colunas referenciadas ainda
    existem upstream.

    Retorna ``{"schema": [...], "node_id": "...", "predicted": true}`` quando
    a inferência é possível, ou ``{"schema": null, "predicted": false}`` quando
    o schema só pode ser determinado após execução real.
    """
    result = await db.execute(
        sa_select(Workflow.definition).where(Workflow.id == workflow_id)
    )
    definition = result.scalar_one_or_none()
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])

    node_map: dict[str, dict] = {str(n["id"]): n for n in nodes if "id" in n}
    if node_id not in node_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No '{node_id}' nao encontrado no workflow.",
        )

    # Pre-resolve connection strings para que sql_database possa probar via
    # SELECT...LIMIT 0. Best-effort: se falhar, sql_database vira None.
    connection_strings: dict[str, str] = {}
    try:
        from app.services.connection_service import connection_service  # noqa: PLC0415
        ws_result = await db.execute(
            sa_select(Workflow.workspace_id, Workflow.project_id).where(
                Workflow.id == workflow_id
            )
        )
        ws_row = ws_result.first()
        if ws_row is not None:
            workspace_id, project_id = ws_row
            connection_strings = await connection_service.resolve_for_workflow(
                db=db,
                definition=definition,
                project_id=project_id,
                workspace_id=workspace_id,
            )
    except Exception:  # noqa: BLE001
        connection_strings = {}

    # Propagação de schema pelo grafo até o nó alvo.
    try:
        schema = _propagate_schema(node_id, node_map, edges, connection_strings)
    except Exception:  # noqa: BLE001
        schema = None

    if schema is None:
        return {"node_id": node_id, "schema": None, "predicted": False}

    return {
        "node_id": node_id,
        "schema": [f.model_dump() for f in schema],
        "predicted": True,
    }


def _propagate_schema(
    target_node_id: str,
    node_map: dict[str, dict],
    edges: list[dict],
    connection_strings: dict[str, str] | None = None,
) -> "list | None":
    """Propaga schemas desde os nós raiz até target_node_id por BFS.

    ``connection_strings`` (opcional) é repassado a predict_output_schema
    para que sql_database possa fazer probe via SELECT...LIMIT 0.
    """
    from collections import defaultdict  # noqa: PLC0415
    from app.services.workflow.schema_inference import predict_output_schema, FieldDescriptor  # noqa: PLC0415

    # Adjacência reversa: node → lista de (source_id, handle)
    reverse: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for e in edges:
        src, tgt = str(e.get("source", "")), str(e.get("target", ""))
        handle = e.get("targetHandle") or None
        if src and tgt:
            reverse[tgt].append((src, handle))

    # Memoização de schemas computados.
    cache: dict[str, list[FieldDescriptor] | None] = {}

    def compute(nid: str) -> list[FieldDescriptor] | None:
        if nid in cache:
            return cache[nid]
        node = node_map.get(nid)
        if node is None:
            cache[nid] = None
            return None

        node_data = node.get("data", {}) if isinstance(node.get("data"), dict) else {}
        node_type = str(node_data.get("type") or node.get("type") or "")

        # Resolve schemas dos upstreams.
        input_schemas: dict[str, list[FieldDescriptor]] = {}
        for src_id, handle in reverse.get(nid, []):
            upstream_schema = compute(src_id)
            if upstream_schema is not None:
                key = handle or "input"
                input_schemas[key] = upstream_schema

        schema = predict_output_schema(
            node_type,
            node_data,
            input_schemas,
            connection_strings=connection_strings,
        )
        cache[nid] = schema
        return schema

    return compute(target_node_id)

