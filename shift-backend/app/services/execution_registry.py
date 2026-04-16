"""
Registry em memoria para tasks asyncio de execucoes de workflow.

Alem do rastreio para cancelamento, mantemos um heartbeat por execucao:
uma task em background atualiza ``workflow_executions.updated_at`` a
cada ``HEARTBEAT_INTERVAL`` segundos. Isso permite que o cleanup no
startup distinga entre "ainda rodando em outro processo" e "morto".

Observacao: o registry vive apenas no processo atual. Para cancelamento
distribuido em multiplos workers a gente precisaria de um mecanismo
externo (fila, flag no DB, etc.) — fora do escopo desta fase.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update

from app.core.logging import get_logger


logger = get_logger(__name__)


HEARTBEAT_INTERVAL_SECONDS = 30


_tasks: dict[UUID, asyncio.Task] = {}
_heartbeat_tasks: dict[UUID, asyncio.Task] = {}
_lock = asyncio.Lock()


async def _heartbeat_loop(execution_id: UUID) -> None:
    """
    Atualiza ``updated_at`` da execucao periodicamente enquanto a task
    principal esta viva. Cancelada via ``asyncio.CancelledError`` quando
    o callback de ``unregister`` e disparado.

    Le ``HEARTBEAT_INTERVAL_SECONDS`` em runtime para permitir que testes
    ajustem o intervalo sem re-importar o modulo.
    """
    # Imports tardios para evitar ciclo no startup.
    from app.db.session import async_session_factory
    from app.models.workflow import WorkflowExecution

    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                async with async_session_factory() as session:
                    await session.execute(
                        update(WorkflowExecution)
                        .where(WorkflowExecution.id == execution_id)
                        .values(updated_at=datetime.now(timezone.utc))
                    )
                    await session.commit()
            except Exception as exc:  # noqa: BLE001 — heartbeat nunca deve derrubar a execucao
                logger.warning(
                    "execution.heartbeat.failed",
                    execution_id=str(execution_id),
                    error=str(exc),
                )
    except asyncio.CancelledError:
        pass


async def register(execution_id: UUID, task: asyncio.Task) -> None:
    """
    Registra a task da execucao e inicia o heartbeat.

    O callback ``add_done_callback`` remove a task do registry e cancela
    o heartbeat quando a execucao termina (sucesso, erro ou cancelamento),
    evitando vazamento de entradas caso o ``finally`` do runner nao rode.
    """
    heartbeat = asyncio.create_task(
        _heartbeat_loop(execution_id),
        name=f"execution-heartbeat-{execution_id}",
    )
    async with _lock:
        _tasks[execution_id] = task
        _heartbeat_tasks[execution_id] = heartbeat

    task.add_done_callback(
        lambda _t, eid=execution_id: asyncio.create_task(unregister(eid))
    )


async def unregister(execution_id: UUID) -> None:
    """Remove a task do registry e cancela o heartbeat (idempotente)."""
    async with _lock:
        _tasks.pop(execution_id, None)
        heartbeat = _heartbeat_tasks.pop(execution_id, None)
    if heartbeat is not None and not heartbeat.done():
        heartbeat.cancel()


async def cancel(execution_id: UUID) -> bool:
    """
    Solicita cancelamento da execucao. Retorna True se achou uma task
    viva e chamou ``cancel()``; False caso contrario (nao registrada,
    ja finalizada ou ja cancelada).
    """
    async with _lock:
        task = _tasks.get(execution_id)

    if task is None:
        logger.info("execution.cancel.not_found", execution_id=str(execution_id))
        return False

    if task.done():
        logger.info("execution.cancel.already_done", execution_id=str(execution_id))
        return False

    task.cancel()
    logger.info("execution.cancel.requested", execution_id=str(execution_id))
    return True


async def is_running(execution_id: UUID) -> bool:
    """Retorna True se a execucao esta registrada e nao concluiu."""
    async with _lock:
        task = _tasks.get(execution_id)
    return task is not None and not task.done()


def list_running() -> list[UUID]:
    """
    Lista IDs de execucoes com task ativa neste processo.

    Sincrona: le apenas o dict (atomico em CPython) para poder ser
    chamada de endpoints sem precisar esperar o lock.
    """
    return [eid for eid, task in _tasks.items() if not task.done()]
