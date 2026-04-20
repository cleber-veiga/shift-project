"""
Tools do Platform Agent relacionadas a projetos e membros.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.project import ProjectCreate
from app.services.agent.base import (
    AgentNotFoundError,
    AgentToolError,
    AgentValidationError,
    require_workspace_role,
    sanitize_llm_string,
)
from app.services.agent.context import UserContext
from app.services.b2b_service import b2b_service
from app.services.connection_service import connection_service
from app.services.workflow_crud_service import workflow_crud_service


async def list_projects(
    *,
    db: AsyncSession,
    ctx: UserContext,
    limit: int = 20,
) -> str:
    """Lista projetos do workspace atual visiveis ao usuario."""
    require_workspace_role(ctx, "VIEWER")

    projects = await b2b_service.list_projects_for_user(
        db, ctx.workspace_id, ctx.user_id
    )
    if not projects:
        return "Nenhum projeto encontrado no workspace."

    limit = max(1, min(int(limit), 100))
    projects = projects[:limit]

    lines = [f"{'Nome':<42} {'ID':<38} Descricao"]
    lines.append("-" * 100)
    for p in projects:
        desc = (p.description or "")[:30]
        lines.append(f"{p.name[:42]:<42} {str(p.id):<38} {desc}")
    return "\n".join(lines)


async def get_project(
    *,
    db: AsyncSession,
    ctx: UserContext,
    project_id: str,
) -> str:
    """Retorna detalhes de um projeto, incluindo contagem de workflows e conexoes."""
    require_workspace_role(ctx, "VIEWER")
    try:
        pid = UUID(project_id)
    except ValueError:
        raise AgentValidationError(f"project_id invalido: '{project_id}'")

    project = await b2b_service.get_project_for_user(db, pid, ctx.user_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise AgentNotFoundError(f"Projeto '{project_id}' nao encontrado.")

    workflows = await workflow_crud_service.list_for_project(db, pid)
    connections = await connection_service.list_for_project(
        db, pid, ctx.workspace_id, ctx.user_id
    )

    lines = [
        f"ID:          {project.id}",
        f"Nome:        {project.name}",
        f"Descricao:   {project.description or '—'}",
        f"Workspace:   {project.workspace_id}",
        f"Workflows:   {len(workflows)}",
        f"Conexoes:    {len(connections)}",
        f"Criado em:   {project.created_at.isoformat() if project.created_at else '—'}",
    ]
    return "\n".join(lines)


async def create_project(
    *,
    db: AsyncSession,
    ctx: UserContext,
    name: str,
    description: str | None = None,
) -> str:
    """Cria um novo projeto no workspace atual (requer aprovacao humana previa)."""
    require_workspace_role(ctx, "MANAGER")

    safe_name = sanitize_llm_string(name)
    safe_desc = sanitize_llm_string(description) if description else None

    if not safe_name:
        raise AgentValidationError("Nome do projeto nao pode ser vazio.")

    data = ProjectCreate(name=safe_name, description=safe_desc)
    try:
        project = await b2b_service.create_project(db, ctx.workspace_id, data)
        await db.commit()
    except ValueError as exc:
        raise AgentToolError(str(exc)) from exc

    return (
        f"Projeto criado com sucesso.\n"
        f"id:   {project.id}\n"
        f"nome: {project.name}"
    )


async def list_project_members(
    *,
    db: AsyncSession,
    ctx: UserContext,
    project_id: str,
) -> str:
    """Lista membros de um projeto com seus roles."""
    require_workspace_role(ctx, "CONSULTANT")
    try:
        pid = UUID(project_id)
    except ValueError:
        raise AgentValidationError(f"project_id invalido: '{project_id}'")

    project = await b2b_service.get_project_for_user(db, pid, ctx.user_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise AgentNotFoundError(f"Projeto '{project_id}' nao encontrado.")

    members = await b2b_service.list_project_members(db, pid)
    if not members:
        return f"Projeto '{project.name}' nao possui membros cadastrados."

    lines = [f"Membros do projeto '{project.name}':"]
    lines.append(f"{'Email':<40} {'Role':<10} Membro desde")
    lines.append("-" * 72)
    for m in members:
        since = m.created_at.isoformat() if m.created_at else "—"
        lines.append(f"{m.email[:40]:<40} {m.role:<10} {since}")
    return "\n".join(lines)
