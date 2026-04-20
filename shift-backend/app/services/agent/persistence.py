"""
Helpers de persistencia do Platform Agent.

Centraliza writes nas tabelas agent_threads, agent_approvals e agent_audit_log.
Nao escreve em agent_messages — isso sera responsabilidade da camada de API
(Fase 3), ja que nos do grafo mantem seu proprio historico via checkpointer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent_approval import AgentApproval
from app.models.agent_audit_log import AgentAuditLog
from app.models.agent_thread import AgentThread


async def create_approval(
    db: AsyncSession,
    *,
    thread_id: UUID,
    proposed_plan: dict[str, Any],
) -> UUID:
    """Cria registro em agent_approvals com status pending e retorna o id."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.AGENT_APPROVAL_TIMEOUT_SECONDS
    )
    row = AgentApproval(
        thread_id=thread_id,
        proposed_plan=proposed_plan,
        status="pending",
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return row.id


async def mark_approval_decision(
    db: AsyncSession,
    *,
    approval_id: UUID,
    approved: bool,
    decided_by: UUID,
    rejection_reason: str | None = None,
) -> None:
    """Atualiza agent_approvals com a decisao humana."""
    stmt = (
        update(AgentApproval)
        .where(AgentApproval.id == approval_id)
        .values(
            status="approved" if approved else "rejected",
            decided_by=decided_by,
            decided_at=datetime.now(timezone.utc),
            rejection_reason=rejection_reason,
        )
    )
    await db.execute(stmt)
    await db.commit()


async def write_audit_log(
    db: AsyncSession,
    *,
    thread_id: UUID,
    user_id: UUID,
    tool_name: str,
    tool_arguments: dict[str, Any],
    status: str,
    approval_id: UUID | None = None,
    tool_result_preview: str | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
    log_metadata: dict[str, Any] | None = None,
) -> UUID:
    """Insere um registro imutavel em agent_audit_log.

    log_metadata armazena avisos do sanitizer e outros dados de seguranca;
    tool_result_preview guarda o RAW (humano precisa ver o real).
    """
    row = AgentAuditLog(
        thread_id=thread_id,
        approval_id=approval_id,
        user_id=user_id,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        tool_result_preview=tool_result_preview,
        status=status,
        error_message=error_message,
        duration_ms=duration_ms,
        log_metadata=log_metadata,
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return row.id


async def ensure_thread(
    db: AsyncSession,
    *,
    thread_id: UUID,
    user_id: UUID,
    workspace_id: UUID,
    project_id: UUID | None,
    initial_context: dict[str, Any],
    title: str | None = None,
) -> None:
    """Cria a thread se ainda nao existir. Idempotente."""
    existing = await db.get(AgentThread, thread_id)
    if existing is not None:
        return
    row = AgentThread(
        id=thread_id,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
        title=title,
        status="running",
        initial_context=initial_context,
    )
    db.add(row)
    await db.flush()
    await db.commit()


async def update_thread_status(
    db: AsyncSession,
    *,
    thread_id: UUID,
    status: str,
) -> None:
    """Atualiza status da thread (running | awaiting_approval | completed | failed)."""
    stmt = (
        update(AgentThread)
        .where(AgentThread.id == thread_id)
        .values(status=status)
    )
    await db.execute(stmt)
    await db.commit()
