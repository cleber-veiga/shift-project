"""
Servico de orcamentos (budgets) do Platform Agent.

Janela deslizante (sliding window) implementada via queries agregadas
no Postgres. Sem Redis por ora — considerar migracao quando o volume
por workspace passar de ~10k mensagens/dia.

Contadores:
- messages: count de agent_messages role=user nas ultimas 1h e 24h,
  escopo por workspace (via JOIN com agent_threads).
- destructive executions: count de agent_audit_log cujo approval_id
  nao e nulo (requires_approval=True gerou aprovacao).
- tokens: soma de metadata->>'total_tokens' em agent_messages
  (thread-scoped para soft cap; user/dia para hard cap).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Numeric, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_approval import AgentApproval
from app.models.agent_audit_log import AgentAuditLog
from app.models.agent_message import AgentMessage
from app.models.agent_thread import AgentThread
from app.services.agent.safety.budget_config import (
    AgentBudget,
    get_budget_for_workspace,
)

logger = get_logger(__name__)


@dataclass
class BudgetCheckResult:
    """Resultado de verificacao de orcamento (nao bloqueia, apenas reporta)."""

    ok: bool
    reason: str | None = None
    retry_after_seconds: int | None = None


@dataclass
class TokenBudgetResult:
    """Resultado para tokens: per-thread soft, per-user-day hard."""

    ok: bool
    reason: str | None = None
    retry_after_seconds: int | None = None
    thread_tokens: int = 0
    user_day_tokens: int = 0


def _retry_after_from_window(
    *,
    now: datetime,
    window_seconds: int,
    db: AsyncSession,
    stmt_oldest: Any,
) -> int:
    """Fallback simples: retry apos o fim da janela atual."""
    _ = (db, stmt_oldest)
    return window_seconds


class AgentBudgetService:
    """Janela deslizante + enforcement por workspace."""

    # ------------------------------------------------------------------
    # Mensagens
    # ------------------------------------------------------------------
    async def check_message_budget(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
    ) -> BudgetCheckResult:
        budget = get_budget_for_workspace(workspace_id)
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)

        count_hour = await self._count_user_messages(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            since=one_hour_ago,
        )
        if count_hour >= budget.messages_per_hour:
            oldest = await self._oldest_message_since(
                db, user_id=user_id, workspace_id=workspace_id, since=one_hour_ago
            )
            retry_after = self._retry_after_from_oldest(
                oldest=oldest, window_seconds=3600, now=now
            )
            return BudgetCheckResult(
                ok=False,
                reason=(
                    f"Limite de mensagens/hora excedido "
                    f"({count_hour}/{budget.messages_per_hour})."
                ),
                retry_after_seconds=retry_after,
            )

        count_day = await self._count_user_messages(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            since=one_day_ago,
        )
        if count_day >= budget.messages_per_day:
            oldest = await self._oldest_message_since(
                db, user_id=user_id, workspace_id=workspace_id, since=one_day_ago
            )
            retry_after = self._retry_after_from_oldest(
                oldest=oldest, window_seconds=86_400, now=now
            )
            return BudgetCheckResult(
                ok=False,
                reason=(
                    f"Limite de mensagens/dia excedido "
                    f"({count_day}/{budget.messages_per_day})."
                ),
                retry_after_seconds=retry_after,
            )

        return BudgetCheckResult(ok=True)

    # ------------------------------------------------------------------
    # Execucoes destrutivas
    # ------------------------------------------------------------------
    async def check_destructive_budget(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
    ) -> BudgetCheckResult:
        budget = get_budget_for_workspace(workspace_id)
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)

        count_hour = await self._count_destructive(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            since=one_hour_ago,
        )
        if count_hour >= budget.destructive_executions_per_hour:
            return BudgetCheckResult(
                ok=False,
                reason=(
                    f"Limite de execucoes destrutivas/hora excedido "
                    f"({count_hour}/{budget.destructive_executions_per_hour})."
                ),
                retry_after_seconds=3600,
            )

        count_day = await self._count_destructive(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            since=one_day_ago,
        )
        if count_day >= budget.destructive_executions_per_day:
            return BudgetCheckResult(
                ok=False,
                reason=(
                    f"Limite de execucoes destrutivas/dia excedido "
                    f"({count_day}/{budget.destructive_executions_per_day})."
                ),
                retry_after_seconds=86_400,
            )

        return BudgetCheckResult(ok=True)

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------
    async def check_token_budget(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID | None,
        workspace_id: UUID,
    ) -> TokenBudgetResult:
        budget = get_budget_for_workspace(workspace_id)
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)

        user_day = await self._sum_tokens(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            since=one_day_ago,
        )
        if user_day >= budget.tokens_per_user_per_day:
            return TokenBudgetResult(
                ok=False,
                reason=(
                    f"Limite de tokens/dia excedido "
                    f"({user_day}/{budget.tokens_per_user_per_day})."
                ),
                retry_after_seconds=86_400,
                user_day_tokens=user_day,
            )

        thread_tokens = 0
        if thread_id is not None:
            thread_tokens = await self._sum_tokens_in_thread(
                db, thread_id=thread_id
            )
            if thread_tokens >= budget.tokens_per_thread:
                return TokenBudgetResult(
                    ok=True,
                    reason=(
                        f"Thread atingiu o limite de {budget.tokens_per_thread} "
                        f"tokens. Inicie uma nova conversa para continuar."
                    ),
                    thread_tokens=thread_tokens,
                    user_day_tokens=user_day,
                )

        return TokenBudgetResult(
            ok=True,
            thread_tokens=thread_tokens,
            user_day_tokens=user_day,
        )

    async def record_tokens(
        self,
        db: AsyncSession,
        *,
        message_id: UUID,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> None:
        """Atualiza metadata JSONB com a contagem de tokens."""
        message = await db.get(AgentMessage, message_id)
        if message is None:
            return
        existing = dict(message.msg_metadata or {})
        existing["prompt_tokens"] = int(prompt_tokens)
        existing["completion_tokens"] = int(completion_tokens)
        existing["total_tokens"] = int(prompt_tokens) + int(completion_tokens)
        existing["model"] = model
        message.msg_metadata = existing
        await db.flush()
        await db.commit()

    # ------------------------------------------------------------------
    # Queries de baixo nivel
    # ------------------------------------------------------------------
    async def _count_user_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        since: datetime,
    ) -> int:
        stmt = (
            select(func.count(AgentMessage.id))
            .select_from(AgentMessage)
            .join(AgentThread, AgentThread.id == AgentMessage.thread_id)
            .where(
                and_(
                    AgentThread.user_id == user_id,
                    AgentThread.workspace_id == workspace_id,
                    AgentMessage.role == "user",
                    AgentMessage.created_at >= since,
                )
            )
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _oldest_message_since(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        since: datetime,
    ) -> datetime | None:
        stmt = (
            select(func.min(AgentMessage.created_at))
            .select_from(AgentMessage)
            .join(AgentThread, AgentThread.id == AgentMessage.thread_id)
            .where(
                and_(
                    AgentThread.user_id == user_id,
                    AgentThread.workspace_id == workspace_id,
                    AgentMessage.role == "user",
                    AgentMessage.created_at >= since,
                )
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _count_destructive(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        since: datetime,
    ) -> int:
        stmt = (
            select(func.count(AgentAuditLog.id))
            .select_from(AgentAuditLog)
            .join(AgentThread, AgentThread.id == AgentAuditLog.thread_id)
            .where(
                and_(
                    AgentAuditLog.user_id == user_id,
                    AgentThread.workspace_id == workspace_id,
                    AgentAuditLog.approval_id.is_not(None),
                    AgentAuditLog.created_at >= since,
                )
            )
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _sum_tokens(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        since: datetime,
    ) -> int:
        total_expr = cast(
            AgentMessage.msg_metadata["total_tokens"].astext,
            Numeric,
        )
        stmt = (
            select(func.coalesce(func.sum(total_expr), 0))
            .select_from(AgentMessage)
            .join(AgentThread, AgentThread.id == AgentMessage.thread_id)
            .where(
                and_(
                    AgentThread.user_id == user_id,
                    AgentThread.workspace_id == workspace_id,
                    AgentMessage.created_at >= since,
                    AgentMessage.msg_metadata["total_tokens"].isnot(None),
                )
            )
        )
        try:
            result = await db.execute(stmt)
            value = result.scalar_one()
            return int(value or 0)
        except Exception:  # noqa: BLE001
            logger.exception("agent.budget.sum_tokens_failed")
            return 0

    async def _sum_tokens_in_thread(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
    ) -> int:
        total_expr = cast(
            AgentMessage.msg_metadata["total_tokens"].astext,
            Numeric,
        )
        stmt = (
            select(func.coalesce(func.sum(total_expr), 0))
            .where(
                and_(
                    AgentMessage.thread_id == thread_id,
                    AgentMessage.msg_metadata["total_tokens"].isnot(None),
                )
            )
        )
        try:
            result = await db.execute(stmt)
            value = result.scalar_one()
            return int(value or 0)
        except Exception:  # noqa: BLE001
            logger.exception("agent.budget.sum_tokens_thread_failed")
            return 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _retry_after_from_oldest(
        *, oldest: datetime | None, window_seconds: int, now: datetime
    ) -> int:
        if oldest is None:
            return window_seconds
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        elapsed = (now - oldest).total_seconds()
        remaining = max(1, int(math.ceil(window_seconds - elapsed)))
        return remaining


agent_budget_service = AgentBudgetService()
