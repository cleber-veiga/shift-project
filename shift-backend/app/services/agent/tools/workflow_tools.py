"""
Tools do Platform Agent relacionadas a workflows e execucoes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.workflow import Workflow, WorkflowExecution
from app.services import execution_registry
from app.services.agent.base import (
    AgentNotFoundError,
    AgentValidationError,
    require_project_role,
    require_workspace_role,
)
from app.services.agent.context import UserContext
from app.services.b2b_service import b2b_service
from app.services.workflow_crud_service import workflow_crud_service
from app.services.workflow_service import workflow_service

# ---------------------------------------------------------------------------
# Helper de escopo
# ---------------------------------------------------------------------------


async def _assert_workflow_in_scope(
    db: AsyncSession,
    wf: Workflow,
    ctx: UserContext,
) -> None:
    """Levanta AgentNotFoundError se o workflow nao pertencer ao workspace do usuario."""
    if wf.workspace_id == ctx.workspace_id:
        return
    if wf.project_id is not None:
        project = await b2b_service.get_project_for_user(db, wf.project_id, ctx.user_id)
        if project is not None and project.workspace_id == ctx.workspace_id:
            return
    raise AgentNotFoundError("Workflow nao encontrado.")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def list_workflows(
    *,
    db: AsyncSession,
    ctx: UserContext,
    project_id: str | None = None,
    limit: int = 20,
) -> str:
    """Lista workflows do projeto ou workspace atual."""
    require_workspace_role(ctx, "VIEWER")

    if project_id is not None:
        try:
            pid = UUID(project_id)
        except ValueError:
            raise AgentValidationError(f"project_id invalido: '{project_id}'")
        project = await b2b_service.get_project_for_user(db, pid, ctx.user_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise AgentNotFoundError(f"Projeto '{project_id}' nao encontrado.")
        workflows = await workflow_crud_service.list_for_project(db, pid)
    elif ctx.project_id is not None:
        workflows = await workflow_crud_service.list_for_project(db, ctx.project_id)
    else:
        workflows = await workflow_crud_service.list_for_workspace(db, ctx.workspace_id)

    if not workflows:
        return "Nenhum workflow encontrado."

    limit = max(1, min(int(limit), 100))
    workflows = workflows[:limit]

    lines = [f"{'Nome':<42} {'Status':<12} ID"]
    lines.append("-" * 82)
    for wf in workflows:
        lines.append(f"{wf.name[:42]:<42} {wf.status:<12} {wf.id}")
    return "\n".join(lines)


async def get_workflow(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
) -> str:
    """Retorna detalhes completos de um workflow."""
    require_workspace_role(ctx, "VIEWER")
    try:
        wid = UUID(workflow_id)
    except ValueError:
        raise AgentValidationError(f"workflow_id invalido: '{workflow_id}'")

    wf = await workflow_crud_service.get(db, wid)
    if wf is None:
        raise AgentNotFoundError(f"Workflow '{workflow_id}' nao encontrado.")
    await _assert_workflow_in_scope(db, wf, ctx)

    definition = wf.definition if isinstance(wf.definition, dict) else {}
    node_count = len(definition.get("nodes") or [])

    lines = [
        f"ID:          {wf.id}",
        f"Nome:        {wf.name}",
        f"Descricao:   {wf.description or '—'}",
        f"Status:      {wf.status}",
        f"Template:    {'Sim' if wf.is_template else 'Nao'}",
        f"Publicado:   {'Sim' if wf.is_published else 'Nao'}",
        f"Nos:         {node_count}",
        f"Criado em:   {wf.created_at.isoformat() if wf.created_at else '—'}",
    ]
    return "\n".join(lines)


async def execute_workflow(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    trigger_params: dict[str, Any] | None = None,
) -> str:
    """Dispara execucao de workflow (requer aprovacao humana previa)."""
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")
    try:
        wid = UUID(workflow_id)
    except ValueError:
        raise AgentValidationError(f"workflow_id invalido: '{workflow_id}'")

    wf = await workflow_crud_service.get(db, wid)
    if wf is None:
        raise AgentNotFoundError(f"Workflow '{workflow_id}' nao encontrado.")
    await _assert_workflow_in_scope(db, wf, ctx)

    try:
        response = await workflow_service.run(
            db=db,
            workflow_id=wf.id,
            triggered_by="agent",
            input_data=trigger_params or {},
        )
    except ValueError as exc:
        raise AgentNotFoundError(str(exc)) from exc

    return (
        f"Execucao iniciada com sucesso.\n"
        f"execution_id: {response.execution_id}\n"
        f"status:       {response.status}\n"
        f"Use get_execution_status para acompanhar o progresso."
    )


async def get_execution_status(
    *,
    db: AsyncSession,
    ctx: UserContext,
    execution_id: str,
) -> str:
    """Retorna o status atual de uma execucao de workflow."""
    require_workspace_role(ctx, "VIEWER")
    try:
        eid = UUID(execution_id)
    except ValueError:
        raise AgentValidationError(f"execution_id invalido: '{execution_id}'")

    stmt = (
        select(WorkflowExecution, Workflow)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .outerjoin(Project, Project.id == Workflow.project_id)
        .where(
            WorkflowExecution.id == eid,
            or_(
                Workflow.workspace_id == ctx.workspace_id,
                Project.workspace_id == ctx.workspace_id,
            ),
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise AgentNotFoundError(f"Execucao '{execution_id}' nao encontrada.")

    exec_, wf = row
    lines = [
        f"execution_id: {exec_.id}",
        f"workflow:     {wf.name} ({wf.id})",
        f"status:       {exec_.status}",
        f"disparado:    {exec_.triggered_by}",
        f"iniciado em:  {exec_.started_at.isoformat() if exec_.started_at else '—'}",
        f"concluido em: {exec_.completed_at.isoformat() if exec_.completed_at else '—'}",
    ]
    if exec_.error_message:
        lines.append(f"erro:         {exec_.error_message}")
    return "\n".join(lines)


async def list_recent_executions(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    limit: int = 10,
) -> str:
    """Lista as ultimas execucoes de um workflow."""
    require_workspace_role(ctx, "VIEWER")
    try:
        wid = UUID(workflow_id)
    except ValueError:
        raise AgentValidationError(f"workflow_id invalido: '{workflow_id}'")

    wf = await workflow_crud_service.get(db, wid)
    if wf is None:
        raise AgentNotFoundError(f"Workflow '{workflow_id}' nao encontrado.")
    await _assert_workflow_in_scope(db, wf, ctx)

    limit = max(1, min(int(limit), 50))
    stmt = (
        select(WorkflowExecution)
        .where(WorkflowExecution.workflow_id == wf.id)
        .order_by(WorkflowExecution.started_at.desc())
        .limit(limit)
    )
    executions = list((await db.execute(stmt)).scalars().all())

    if not executions:
        return f"Nenhuma execucao encontrada para o workflow '{wf.name}'."

    lines = [f"Ultimas execucoes de '{wf.name}':"]
    lines.append(f"{'ID':<38} {'Status':<12} Iniciado em")
    lines.append("-" * 80)
    for ex in executions:
        started = ex.started_at.isoformat() if ex.started_at else "—"
        lines.append(f"{str(ex.id):<38} {ex.status:<12} {started}")
    return "\n".join(lines)


async def cancel_execution(
    *,
    db: AsyncSession,
    ctx: UserContext,
    execution_id: str,
) -> str:
    """Solicita cancelamento de execucao em andamento (requer aprovacao humana previa)."""
    require_workspace_role(ctx, "CONSULTANT")
    try:
        eid = UUID(execution_id)
    except ValueError:
        raise AgentValidationError(f"execution_id invalido: '{execution_id}'")

    stmt = (
        select(WorkflowExecution, Workflow)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .outerjoin(Project, Project.id == Workflow.project_id)
        .where(
            WorkflowExecution.id == eid,
            or_(
                Workflow.workspace_id == ctx.workspace_id,
                Project.workspace_id == ctx.workspace_id,
            ),
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise AgentNotFoundError(f"Execucao '{execution_id}' nao encontrada.")

    exec_, _ = row
    if exec_.status != "RUNNING":
        return (
            f"Execucao '{execution_id}' nao esta em andamento "
            f"(status atual: {exec_.status})."
        )

    cancelled = await execution_registry.cancel(eid)
    if cancelled:
        return (
            f"Cancelamento solicitado para execucao '{execution_id}'. "
            "O status sera atualizado em breve."
        )
    return (
        f"Execucao '{execution_id}' nao encontrada no registry local "
        "(pode ter finalizado antes do cancelamento ser processado)."
    )
