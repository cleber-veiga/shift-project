"""
Tools do Platform Agent relacionadas a conexoes de banco de dados.

IMPORTANTE: nenhuma destas tools retorna credenciais, senhas,
connection strings ou quaisquer campos sensiveis ao LLM.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.base import (
    AgentNotFoundError,
    AgentToolError,
    AgentValidationError,
    require_workspace_role,
)
from app.services.agent.context import UserContext
from app.services.b2b_service import b2b_service
from app.services.connection_service import connection_service

# Campos que NUNCA devem aparecer na resposta ao LLM
_SENSITIVE_FIELDS = frozenset(
    {"password", "connection_string", "secret", "token", "api_key", "credential"}
)


def _format_connection_safe(conn) -> str:
    """Formata apenas os metadados nao-sensiveis de uma conexao."""
    lines = [
        f"ID:          {conn.id}",
        f"Nome:        {conn.name}",
        f"Tipo:        {conn.type}",
        f"Host:        {conn.host or '—'}",
        f"Porta:       {conn.port or '—'}",
        f"Banco:       {conn.database or '—'}",
        f"Usuario:     {conn.username or '—'}",
        f"Publica:     {'Sim' if conn.is_public else 'Nao'}",
    ]
    if conn.workspace_id:
        lines.append(f"Workspace:   {conn.workspace_id}")
    if conn.project_id:
        lines.append(f"Projeto:     {conn.project_id}")
    return "\n".join(lines)


async def _assert_connection_in_scope(db: AsyncSession, conn, ctx: UserContext) -> None:
    """Levanta AgentNotFoundError se a conexao nao pertencer ao workspace do usuario."""
    ws_id = conn.workspace_id
    if ws_id is None and conn.project_id is not None:
        project = await b2b_service.get_project_for_user(
            db, conn.project_id, ctx.user_id
        )
        if project is not None:
            ws_id = project.workspace_id

    if ws_id != ctx.workspace_id:
        raise AgentNotFoundError("Conexao nao encontrada.")

    # Visibilidade: publica ou criada pelo proprio usuario
    if not conn.is_public and getattr(conn, "created_by_id", None) != ctx.user_id:
        raise AgentNotFoundError("Conexao nao encontrada.")


async def list_connections(
    *,
    db: AsyncSession,
    ctx: UserContext,
    project_id: str | None = None,
) -> str:
    """Lista conexoes visiveis ao usuario; nunca retorna credenciais."""
    require_workspace_role(ctx, "VIEWER")

    if project_id is not None:
        try:
            pid = UUID(project_id)
        except ValueError:
            raise AgentValidationError(f"project_id invalido: '{project_id}'")
        project = await b2b_service.get_project_for_user(db, pid, ctx.user_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise AgentNotFoundError(f"Projeto '{project_id}' nao encontrado.")
        conns = await connection_service.list_for_project(
            db, pid, ctx.workspace_id, ctx.user_id
        )
    elif ctx.project_id is not None:
        conns = await connection_service.list_for_project(
            db, ctx.project_id, ctx.workspace_id, ctx.user_id
        )
    else:
        conns = await connection_service.list(db, ctx.workspace_id, ctx.user_id)

    if not conns:
        return "Nenhuma conexao encontrada."

    lines = [f"{'Nome':<35} {'Tipo':<14} {'Host':<30} ID"]
    lines.append("-" * 100)
    for c in conns:
        host = (c.host or "—")[:30]
        lines.append(
            f"{c.name[:35]:<35} {c.type[:14]:<14} {host:<30} {c.id}"
        )
    return "\n".join(lines)


async def get_connection(
    *,
    db: AsyncSession,
    ctx: UserContext,
    connection_id: str,
) -> str:
    """Retorna metadados nao-sensiveis de uma conexao; nunca retorna senha ou tokens."""
    require_workspace_role(ctx, "VIEWER")
    try:
        cid = UUID(connection_id)
    except ValueError:
        raise AgentValidationError(f"connection_id invalido: '{connection_id}'")

    conn = await connection_service.get(db, cid)
    if conn is None:
        raise AgentNotFoundError(f"Conexao '{connection_id}' nao encontrada.")

    await _assert_connection_in_scope(db, conn, ctx)
    return _format_connection_safe(conn)


async def test_connection(
    *,
    db: AsyncSession,
    ctx: UserContext,
    connection_id: str,
) -> str:
    """Testa a conectividade de uma conexao (read-only, sem aprovacao necessaria)."""
    require_workspace_role(ctx, "CONSULTANT")
    try:
        cid = UUID(connection_id)
    except ValueError:
        raise AgentValidationError(f"connection_id invalido: '{connection_id}'")

    conn = await connection_service.get(db, cid)
    if conn is None:
        raise AgentNotFoundError(f"Conexao '{connection_id}' nao encontrada.")

    await _assert_connection_in_scope(db, conn, ctx)

    try:
        result = await connection_service.test_connection(db, cid)
    except Exception as exc:
        raise AgentToolError(f"Erro ao testar conexao: {exc}") from exc

    status = "SUCESSO" if result.success else "FALHA"
    return f"Resultado: {status}\n{result.message}"
