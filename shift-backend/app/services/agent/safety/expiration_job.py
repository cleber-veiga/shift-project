"""
Job periodico que expira aprovacoes pendentes alem do expires_at.

Rodando a cada 5 minutos via APScheduler. Marca approvals como 'expired'
e atualiza a thread para status 'expired' quando a approval estava
bloqueando. Nao retoma o grafo — o interrupt() fica orfao (aceitavel;
nao cria efeitos colaterais).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.agent_approval import AgentApproval
from app.models.agent_thread import AgentThread

logger = get_logger(__name__)

_JOB_ID = "agent_expire_approvals"


async def expire_pending_approvals() -> dict[str, int]:
    """Expira approvals pendentes cujo expires_at ja passou.

    Retorna dict com contagens (util para logging/testes).
    Idempotente: rodar N vezes em sequencia nao causa efeito duplo.
    """
    now = datetime.now(timezone.utc)
    counters = {"approvals_expired": 0, "threads_expired": 0}

    async with async_session_factory() as db:
        stmt_select = select(AgentApproval.id, AgentApproval.thread_id).where(
            AgentApproval.status == "pending",
            AgentApproval.expires_at < now,
        )
        rows = (await db.execute(stmt_select)).all()

        if not rows:
            return counters

        approval_ids = [r[0] for r in rows]
        thread_ids = list({r[1] for r in rows})

        stmt_update_approvals = (
            update(AgentApproval)
            .where(
                AgentApproval.id.in_(approval_ids),
                AgentApproval.status == "pending",
            )
            .values(status="expired")
        )
        result = await db.execute(stmt_update_approvals)
        counters["approvals_expired"] = int(result.rowcount or 0)

        if thread_ids:
            stmt_update_threads = (
                update(AgentThread)
                .where(
                    AgentThread.id.in_(thread_ids),
                    AgentThread.status == "awaiting_approval",
                )
                .values(status="expired")
            )
            result_t = await db.execute(stmt_update_threads)
            counters["threads_expired"] = int(result_t.rowcount or 0)

        await db.commit()

    logger.info(
        "agent.approvals.expired",
        approvals=counters["approvals_expired"],
        threads=counters["threads_expired"],
    )
    return counters


def register_agent_expiration_job(
    scheduler: AsyncIOScheduler,
    *,
    interval_minutes: int = 5,
) -> None:
    """Registra o job de expiracao no scheduler (a cada N minutos)."""
    scheduler.add_job(
        expire_pending_approvals,
        trigger="interval",
        minutes=max(1, int(interval_minutes)),
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "agent.expiration_job.registered",
        job_id=_JOB_ID,
        interval_minutes=interval_minutes,
    )
