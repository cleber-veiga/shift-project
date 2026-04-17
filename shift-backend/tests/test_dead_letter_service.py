"""Cobertura de dead-letter + partial rows para a fase 5c."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "CHAR(36)"


from sqlalchemy import event  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.workflow import DeadLetterEntry, Workflow, WorkflowExecution  # noqa: E402
from app.services.dead_letter_service import dead_letter_service  # noqa: E402
from app.services.workflow.nodes.bulk_insert import BulkInsertProcessor  # noqa: E402
from app.services.workflow.nodes.dead_letter import DeadLetterProcessor  # noqa: E402
from tests.conftest import create_duckdb_with_rows, read_duckdb_table  # noqa: E402


# Criamos apenas o subconjunto de tabelas que o teste precisa, porque algumas
# outras tabelas (ex.: workflow_versions) declaram server_defaults com
# sintaxe especifica de Postgres ('::jsonb') que o SQLite rejeita.
_TEST_TABLES = [
    Project.__table__,
    Workflow.__table__,
    WorkflowExecution.__table__,
    DeadLetterEntry.__table__,
]


def _register_sqlite_udfs(dbapi_connection, _connection_record) -> None:
    """Registra ``gen_random_uuid`` no SQLite (server_default usado pelos models)."""
    dbapi_connection.create_function(
        "gen_random_uuid",
        0,
        lambda: str(uuid.uuid4()),
    )


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _register_sqlite_udfs)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_TEST_TABLES)
        )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def _seed_execution(db: AsyncSession, definition: dict | None = None) -> WorkflowExecution:
    workflow = Workflow(
        id=uuid.uuid4(),
        name="wf-dead-letter",
        workspace_id=uuid.uuid4(),
        definition=definition or {"nodes": [], "edges": []},
    )
    execution = WorkflowExecution(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        status="RUNNING",
    )
    db.add(workflow)
    db.add(execution)
    await db.commit()
    return execution


def _make_target_sqlite(tmp_path: Path) -> str:
    db_file = tmp_path / "target.sqlite"
    cs = f"sqlite:///{db_file}"
    engine = sa.create_engine(cs)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE clientes (
                        nome VARCHAR(100) NOT NULL UNIQUE
                    )
                    """
                )
            )
    finally:
        engine.dispose()
    return cs


class TestDeadLetterNode:
    @pytest.mark.asyncio
    async def test_dead_letter_writes_entry(
        self,
        tmp_path: Path,
        db: AsyncSession,
        session_factory,
        monkeypatch,
    ) -> None:
        execution = await _seed_execution(db)
        monkeypatch.setattr(
            "app.services.dead_letter_service.async_session_factory",
            session_factory,
        )

        source_ref = create_duckdb_with_rows(
            tmp_path / "dead_letter.duckdb",
            "failed_rows",
            [{"NAME": None, "_dead_letter_error": "nome nao pode ser nulo"}],
        )
        processor = DeadLetterProcessor()
        # process() internamente chama asyncio.run(); para nao conflitar com
        # o event loop do pytest-asyncio, rodamos em thread.
        output = await asyncio.to_thread(
            processor.process,
            "dead-letter-node",
            {"type": "dead_letter"},
            {
                "execution_id": str(execution.id),
                "workflow_id": str(execution.workflow_id),
                "upstream_results": {
                    "bulk-1": {
                        "node_id": "bulk-1",
                        "failed_node": "bulk-1",
                        "error": "falha no insert",
                        "output_field": "data",
                        "data": source_ref,
                    }
                },
            },
        )

        assert output["status"] == "success"
        assert output["entries_written"] == 1

        rows = (await db.execute(select(DeadLetterEntry))).scalars().all()
        assert len(rows) == 1
        assert rows[0].node_id == "bulk-1"
        assert rows[0].payload["NAME"] is None
        assert rows[0].error_message == "nome nao pode ser nulo"


class TestDeadLetterRetry:
    @pytest.mark.asyncio
    async def test_dead_letter_retry_reprocesses(
        self,
        tmp_path: Path,
        db: AsyncSession,
        monkeypatch,
    ) -> None:
        target_cs = _make_target_sqlite(tmp_path)
        workflow_definition = {
            "nodes": [
                {
                    "id": "bulk-1",
                    "type": "bulk_insert",
                    "data": {
                        "type": "bulk_insert",
                        "connection_id": "conn-1",
                        "target_table": "clientes",
                        "column_mapping": [{"source": "NAME", "target": "nome"}],
                    },
                }
            ],
            "edges": [],
        }
        execution = await _seed_execution(db, workflow_definition)
        entry = DeadLetterEntry(
            id=uuid.uuid4(),
            execution_id=execution.id,
            node_id="bulk-1",
            error_message="nome duplicado",
            payload={"NAME": "Alice"},
        )
        db.add(entry)
        await db.commit()

        async def _resolve_connections(*args, **kwargs):
            return {"conn-1": target_cs}

        monkeypatch.setattr(
            "app.services.dead_letter_service.connection_service.resolve_for_workflow",
            _resolve_connections,
        )

        result = await dead_letter_service.retry_entry(db, dead_letter_id=entry.id)
        assert result["resolved"] is True
        assert result["retry_count"] == 1

        await db.refresh(entry)
        assert entry.resolved_at is not None

        engine = sa.create_engine(target_cs)
        try:
            with engine.connect() as conn:
                count = conn.execute(sa.text("SELECT COUNT(*) FROM clientes")).scalar()
                assert count == 1
        finally:
            engine.dispose()


class TestBulkInsertPartialRows:
    def test_bulk_insert_partial_failure_splits_rows(
        self,
        tmp_path: Path,
    ) -> None:
        target_cs = _make_target_sqlite(tmp_path)
        source_ref = create_duckdb_with_rows(
            tmp_path / "bulk_input.duckdb",
            "src",
            [
                {"NAME": "Alice"},
                {"NAME": None},
                {"NAME": "Bob"},
            ],
        )
        processor = BulkInsertProcessor()
        output = processor.process(
            "bulk-1",
            {
                "connection_string": target_cs,
                "target_table": "clientes",
                "column_mapping": [{"source": "NAME", "target": "nome"}],
            },
            {
                "execution_id": str(uuid.uuid4()),
                "workflow_id": str(uuid.uuid4()),
                "upstream_results": {
                    "src": {
                        "node_id": "src",
                        "output_field": "data",
                        "data": source_ref,
                    }
                },
            },
        )

        assert output["status"] == "partial"
        assert output["succeeded_rows_count"] == 2
        assert output["failed_rows_count"] == 1
        assert set(output["active_handles"]) == {"success", "on_error"}

        success_ref = output["branches"]["success"]
        failed_ref = output["branches"]["on_error"]
        success_rows = read_duckdb_table(
            success_ref["database_path"],
            success_ref["table_name"],
        )
        failed_rows = read_duckdb_table(
            failed_ref["database_path"],
            failed_ref["table_name"],
        )

        assert [row["NAME"] for row in success_rows] == ["Alice", "Bob"]
        assert failed_rows[0]["NAME"] is None
        assert failed_rows[0]["_dead_letter_error"]
