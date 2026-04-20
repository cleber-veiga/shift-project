"""
Servico de auditoria do Platform Agent.

Somente-leitura sobre agent_audit_log. Escopo por workspace (JOIN com
agent_threads); filtros por projeto/usuario/tool/status/periodo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_audit_log import AgentAuditLog
from app.models.agent_thread import AgentThread

logger = get_logger(__name__)


@dataclass
class AuditStats:
    """Agregacoes de auditoria de um workspace em um periodo."""

    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    top_tools: list[dict[str, Any]]
    top_users: list[dict[str, Any]]


class AgentAuditService:
    async def list(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
        user_id: UUID | None = None,
        tool_name: str | None = None,
        status: Literal["success", "error"] | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AgentAuditLog], int]:
        """Retorna (entries, total_count) para paginacao."""
        filters = [AgentThread.workspace_id == workspace_id]
        if project_id is not None:
            filters.append(AgentThread.project_id == project_id)
        if user_id is not None:
            filters.append(AgentAuditLog.user_id == user_id)
        if tool_name is not None:
            filters.append(AgentAuditLog.tool_name == tool_name)
        if status is not None:
            filters.append(AgentAuditLog.status == status)
        if from_date is not None:
            filters.append(AgentAuditLog.created_at >= from_date)
        if to_date is not None:
            filters.append(AgentAuditLog.created_at <= to_date)

        stmt_count = (
            select(func.count(AgentAuditLog.id))
            .select_from(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(and_(*filters))
        )
        total = int((await db.execute(stmt_count)).scalar_one() or 0)

        stmt_rows = (
            select(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(and_(*filters))
            .order_by(desc(AgentAuditLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = list((await db.execute(stmt_rows)).scalars().all())
        return rows, total

    async def get_entry(
        self,
        db: AsyncSession,
        *,
        entry_id: UUID,
        workspace_id: UUID,
    ) -> AgentAuditLog | None:
        """Retorna 1 entrada com validacao de escopo (workspace)."""
        stmt = (
            select(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(
                and_(
                    AgentAuditLog.id == entry_id,
                    AgentThread.workspace_id == workspace_id,
                )
            )
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def stats(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
        days: int = 30,
    ) -> AuditStats:
        """Agregacoes: total, taxa sucesso, top tools, top users."""
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        filters = [
            AgentThread.workspace_id == workspace_id,
            AgentAuditLog.created_at >= since,
        ]
        if project_id is not None:
            filters.append(AgentThread.project_id == project_id)

        stmt_counts = (
            select(AgentAuditLog.status, func.count(AgentAuditLog.id))
            .select_from(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(and_(*filters))
            .group_by(AgentAuditLog.status)
        )
        total = 0
        success = 0
        failed = 0
        for row in (await db.execute(stmt_counts)).all():
            status_value, count = row[0], int(row[1])
            total += count
            if status_value == "success":
                success += count
            elif status_value == "error":
                failed += count

        stmt_tools = (
            select(
                AgentAuditLog.tool_name,
                func.count(AgentAuditLog.id).label("count"),
            )
            .select_from(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(and_(*filters))
            .group_by(AgentAuditLog.tool_name)
            .order_by(desc("count"))
            .limit(5)
        )
        top_tools = [
            {"tool_name": r[0], "count": int(r[1])}
            for r in (await db.execute(stmt_tools)).all()
        ]

        stmt_users = (
            select(
                AgentAuditLog.user_id,
                func.count(AgentAuditLog.id).label("count"),
            )
            .select_from(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(and_(*filters))
            .group_by(AgentAuditLog.user_id)
            .order_by(desc("count"))
            .limit(5)
        )
        top_users = [
            {"user_id": str(r[0]), "count": int(r[1])}
            for r in (await db.execute(stmt_users)).all()
        ]

        rate = (success / total) if total > 0 else 0.0
        return AuditStats(
            total_executions=total,
            successful_executions=success,
            failed_executions=failed,
            success_rate=rate,
            top_tools=top_tools,
            top_users=top_users,
        )


agent_audit_service = AgentAuditService()
