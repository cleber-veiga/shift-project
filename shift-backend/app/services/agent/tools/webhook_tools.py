"""
Tools do Platform Agent relacionadas a webhooks.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.base import (
    AgentNotFoundError,
    AgentValidationError,
    require_workspace_role,
)
from app.services.agent.context import UserContext
from app.services.agent.tools.workflow_tools import _assert_workflow_in_scope
from app.services.b2b_service import b2b_service
from app.services.webhook_service import _extract_webhook_nodes
from app.services.workflow_crud_service import workflow_crud_service
from app.services.workflow_service import workflow_service


async def list_webhooks(
    *,
    db: AsyncSession,
    ctx: UserContext,
    project_id: str | None = None,
) -> str:
    """Lista nos webhook configurados nos workflows do projeto ou workspace."""
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

    webhook_entries: list[dict[str, str]] = []
    for wf in workflows:
        for node_id, cfg in _extract_webhook_nodes(wf):
            webhook_entries.append(
                {
                    "workflow_id": str(wf.id),
                    "workflow_name": wf.name,
                    "node_id": node_id,
                    "path": cfg.get("path") or str(wf.id),
                }
            )

    if not webhook_entries:
        return "Nenhum webhook configurado nos workflows em escopo."

    lines = [f"{'Workflow':<35} {'Path':<35} Node ID"]
    lines.append("-" * 90)
    for entry in webhook_entries:
        lines.append(
            f"{entry['workflow_name'][:35]:<35} "
            f"{entry['path'][:35]:<35} "
            f"{entry['node_id']}"
        )
    return "\n".join(lines)


async def trigger_webhook_manually(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    payload: dict[str, Any] | None = None,
) -> str:
    """Simula disparo de webhook em modo de teste (requer aprovacao humana previa)."""
    require_workspace_role(ctx, "CONSULTANT")
    try:
        wid = UUID(workflow_id)
    except ValueError:
        raise AgentValidationError(f"workflow_id invalido: '{workflow_id}'")

    wf = await workflow_crud_service.get(db, wid)
    if wf is None:
        raise AgentNotFoundError(f"Workflow '{workflow_id}' nao encontrado.")
    await _assert_workflow_in_scope(db, wf, ctx)

    nodes = _extract_webhook_nodes(wf)
    if not nodes:
        raise AgentNotFoundError(
            f"Workflow '{wf.name}' nao possui nos webhook configurados."
        )

    response = await workflow_service.run(
        db=db,
        workflow_id=wf.id,
        triggered_by="agent_webhook_test",
        input_data=payload or {},
        mode="test",
    )
    return (
        f"Disparo de teste iniciado para webhook do workflow '{wf.name}'.\n"
        f"execution_id: {response.execution_id}\n"
        f"status:       {response.status}"
    )
