"""
CRUD de threads do Platform Agent.

Mantém agent_threads e lê agent_messages/agent_approvals para o detalhe.
Threads sao privadas ao usuario que as criou — 404 em acesso nao autorizado
(nunca 403, evita enumeration).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_approval import AgentApproval
from app.models.agent_audit_log import AgentAuditLog
from app.models.agent_message import AgentMessage
from app.models.agent_thread import AgentThread
from app.core.logging import get_logger

logger = get_logger(__name__)


class ThreadService:
    """CRUD e leitura de threads do Platform Agent."""

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        initial_context: dict[str, Any],
        title: str | None = None,
    ) -> AgentThread:
        """Cria e persiste uma nova thread com status 'running'."""
        thread = AgentThread(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            title=title,
            status="running",
            initial_context=initial_context,
        )
        db.add(thread)
        await db.flush()
        await db.commit()
        await db.refresh(thread)
        return thread

    async def list_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AgentThread]:
        """Lista threads do usuario no workspace, ordenadas por updated_at desc."""
        stmt = (
            select(AgentThread)
            .where(
                AgentThread.user_id == user_id,
                AgentThread.workspace_id == workspace_id,
            )
            .order_by(AgentThread.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        user_id: UUID,
    ) -> AgentThread:
        """Retorna a thread ou levanta 404 (nunca 403)."""
        stmt = select(AgentThread).where(
            AgentThread.id == thread_id,
            AgentThread.user_id == user_id,
        )
        result = await db.execute(stmt)
        thread = result.scalar_one_or_none()
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread nao encontrada.",
            )
        return thread

    async def get_with_messages(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        user_id: UUID,
    ) -> tuple[AgentThread, list[AgentMessage], AgentApproval | None]:
        """Retorna thread + mensagens + approval pendente em queries separadas."""
        thread = await self.get(db, thread_id=thread_id, user_id=user_id)

        msgs_stmt = (
            select(AgentMessage)
            .where(AgentMessage.thread_id == thread_id)
            .order_by(AgentMessage.created_at.asc())
        )
        msgs_result = await db.execute(msgs_stmt)
        messages = list(msgs_result.scalars().all())

        approval: AgentApproval | None = None
        if thread.status == "awaiting_approval":
            appr_stmt = (
                select(AgentApproval)
                .where(
                    AgentApproval.thread_id == thread_id,
                    AgentApproval.status == "pending",
                )
                .order_by(AgentApproval.created_at.desc())
                .limit(1)
            )
            appr_result = await db.execute(appr_stmt)
            approval = appr_result.scalar_one_or_none()

        return thread, messages, approval

    async def get_pending_approval(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        approval_id: UUID,
    ) -> AgentApproval:
        """Retorna o approval se pertencer a thread e estiver pending; 404 caso contrario."""
        stmt = select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.thread_id == thread_id,
        )
        result = await db.execute(stmt)
        approval = result.scalar_one_or_none()
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aprovacao nao encontrada.",
            )
        if approval.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Aprovacao ja decidida: status '{approval.status}'.",
            )
        now = datetime.now(timezone.utc)
        if approval.expires_at.tzinfo is None:
            # comparacao segura se o banco retornar naive datetime
            from datetime import timezone as _tz
            expires = approval.expires_at.replace(tzinfo=_tz.utc)
        else:
            expires = approval.expires_at
        if now > expires:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Aprovacao expirada.",
            )
        return approval

    async def delete(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        user_id: UUID,
    ) -> None:
        """Remove a thread. Levanta 409 se houver registros de audit_log (RESTRICT FK)."""
        thread = await self.get(db, thread_id=thread_id, user_id=user_id)

        has_audit = await db.scalar(
            select(exists().where(AgentAuditLog.thread_id == thread_id))
        )
        if has_audit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Thread com auditoria nao pode ser apagada.",
            )

        await db.delete(thread)
        await db.commit()

    async def update_status(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        status_value: str,
    ) -> None:
        """Atualiza status da thread diretamente."""
        from sqlalchemy import update
        stmt = (
            update(AgentThread)
            .where(AgentThread.id == thread_id)
            .values(status=status_value)
        )
        await db.execute(stmt)
        await db.commit()

    async def add_message(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        role: str,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        msg_metadata: dict[str, Any] | None = None,
    ) -> AgentMessage:
        """Persiste uma mensagem em agent_messages."""
        msg = AgentMessage(
            thread_id=thread_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            msg_metadata=msg_metadata,
        )
        db.add(msg)
        await db.flush()
        await db.commit()
        await db.refresh(msg)
        return msg


thread_service = ThreadService()
