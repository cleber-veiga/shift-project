"""
Checkpointer do LangGraph para o Platform Agent.

Expoe um singleton de AsyncPostgresSaver sobre psycopg3 + AsyncConnectionPool.
O pool e aberto na primeira chamada e fechado no shutdown da aplicacao.

O AsyncPostgresSaver precisa de uma conexao psycopg3 (nao asyncpg do SQLAlchemy),
por isso convertemos DATABASE_URL para o formato postgresql:// e mantemos um
pool separado exclusivamente para o checkpointer.
"""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_checkpointer: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None
_setup_done: bool = False
_lock = asyncio.Lock()

_SCHEMA_BOOTSTRAP_SQL = (
    """
    CREATE TABLE IF NOT EXISTS checkpoint_migrations (
        v INTEGER PRIMARY KEY
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint JSONB NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoint_blobs (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL,
        version TEXT NOT NULL,
        type TEXT NOT NULL,
        blob BYTEA,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoint_writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        task_path TEXT NOT NULL DEFAULT '',
        idx INTEGER NOT NULL,
        channel TEXT NOT NULL,
        type TEXT,
        blob BYTEA NOT NULL,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    );
    """,
    """
    ALTER TABLE checkpoint_blobs
    ALTER COLUMN blob DROP NOT NULL;
    """,
    """
    ALTER TABLE checkpoint_writes
    ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';
    """,
    """
    CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx
    ON checkpoints(thread_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx
    ON checkpoint_blobs(thread_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx
    ON checkpoint_writes(thread_id);
    """,
)
_LATEST_CHECKPOINT_MIGRATION = 9


def _psycopg_dsn() -> str:
    """Converte DATABASE_URL async (asyncpg) para DSN psycopg3."""
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


async def _ensure_checkpointer_schema(pool: AsyncConnectionPool) -> None:
    """Garante schema compativel do checkpointer sem depender do setup() upstream.

    O setup() do pacote upstream tem se mostrado instavel neste ambiente
    Windows/Neon. Como as tabelas sao simples e o contrato do schema e
    conhecido, aplicamos um bootstrap idempotente local.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            for stmt in _SCHEMA_BOOTSTRAP_SQL:
                await cur.execute(stmt)

            await cur.execute("SELECT v FROM checkpoint_migrations ORDER BY v")
            existing = {int(row[0]) for row in await cur.fetchall()}
            missing = [
                (version,)
                for version in range(_LATEST_CHECKPOINT_MIGRATION + 1)
                if version not in existing
            ]
            if missing:
                await cur.executemany(
                    """
                    INSERT INTO checkpoint_migrations (v)
                    VALUES (%s)
                    ON CONFLICT (v) DO NOTHING
                    """,
                    missing,
                )


async def get_checkpointer() -> AsyncPostgresSaver:
    """Retorna o checkpointer singleton, inicializando na primeira chamada."""
    global _checkpointer, _pool, _setup_done

    if _checkpointer is not None and _setup_done:
        return _checkpointer

    async with _lock:
        if _checkpointer is not None and _setup_done:
            return _checkpointer

        if _pool is None:
            _pool = AsyncConnectionPool(
                conninfo=_psycopg_dsn(),
                max_size=5,
                min_size=1,
                kwargs={"autocommit": True, "prepare_threshold": 0},
                open=False,
            )
            await _pool.open()

        if _checkpointer is None:
            _checkpointer = AsyncPostgresSaver(_pool)  # type: ignore[arg-type]

        if not _setup_done:
            await _ensure_checkpointer_schema(_pool)
            _setup_done = True
            logger.info("agent.checkpointer.ready")

        return _checkpointer


async def close_checkpointer() -> None:
    """Fecha o pool do checkpointer. Chamado no shutdown da aplicacao."""
    global _checkpointer, _pool, _setup_done
    if _pool is not None:
        await _pool.close()
        logger.info("agent.checkpointer.closed")
    _checkpointer = None
    _pool = None
    _setup_done = False
