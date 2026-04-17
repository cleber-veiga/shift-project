"""
Testes dos endpoints da aba "Executions".

Cobre:
- GET /workflows/{workflow_id}/executions (listagem com filtros e paginacao)
- DELETE /workflows/executions/{execution_id}

Para evitar dependencia de Postgres em CI, os testes montam um mini-app
FastAPI com os endpoints reais e substituem a dependencia ``get_db`` por
uma sessao SQLite in-memory. Tipos Postgres (JSONB, UUID) ganham
compiladores SQLite para que ``create_all`` funcione.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


# ---------------------------------------------------------------------------
# Compatibilidade de tipos Postgres -> SQLite (uso somente em teste)
# ---------------------------------------------------------------------------

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "CHAR(36)"


# Importa modelos/endpoints DEPOIS de registrar os compiladores acima.
from app.api.dependencies import get_db  # noqa: E402
from app.api.v1.workflows import (  # noqa: E402
    delete_execution,
    list_workflow_executions,
)
from app.core.security import require_permission  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.workflow import (  # noqa: E402
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
)


# ---------------------------------------------------------------------------
# Fixtures: engine, sessao, app com dependency overrides
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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


@pytest_asyncio.fixture
async def api_client(session_factory):
    """Mini-app FastAPI so com as rotas que queremos testar."""

    app = FastAPI()

    # Permissao e checada via banco real em producao. Em teste, bypass.
    async def _allow() -> None:
        return None

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Registra as duas rotas manualmente em vez de incluir o router inteiro
    # (o router depende de outros services que nao queremos instanciar aqui).
    app.add_api_route(
        "/workflows/{workflow_id}/executions",
        list_workflow_executions,
        methods=["GET"],
    )
    app.add_api_route(
        "/workflows/executions/{execution_id}",
        delete_execution,
        methods=["DELETE"],
        status_code=204,
    )

    app.dependency_overrides[get_db] = _override_get_db
    # ``require_permission`` e uma factory: sobrescrevemos cada instancia
    # referenciada nas rotas pelos seus placeholders. Como FastAPI
    # identifica a dependencia pela funcao retornada, e mais simples
    # sobrescrever a factory por um replacement de alto nivel.
    # Estrategia: procurar cada dependencia registrada e anulla-la.
    for route in app.router.routes:
        if hasattr(route, "dependant"):
            for sub in route.dependant.dependencies:
                if sub.call is not None and getattr(
                    sub.call, "__qualname__", ""
                ).startswith("require_permission"):
                    app.dependency_overrides[sub.call] = _allow

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(db: AsyncSession) -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        name="test",
        workspace_id=uuid.uuid4(),
        definition={"nodes": [], "edges": []},
    )
    db.add(wf)
    return wf


async def _make_execution(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    status: str = "COMPLETED",
    triggered_by: str = "manual",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error_message: str | None = None,
    node_count: int = 0,
) -> WorkflowExecution:
    ex = WorkflowExecution(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        status=status,
        triggered_by=triggered_by,
        started_at=started_at,
        completed_at=completed_at,
        error_message=error_message,
    )
    db.add(ex)
    await db.flush()
    for i in range(node_count):
        db.add(
            WorkflowNodeExecution(
                id=uuid.uuid4(),
                execution_id=ex.id,
                node_id=f"n{i}",
                node_type="mapper",
                status="success",
                duration_ms=10,
            )
        )
    await db.flush()
    return ex


# ---------------------------------------------------------------------------
# Testes de listagem
# ---------------------------------------------------------------------------

class TestListExecutions:
    async def test_empty_list(self, api_client, db) -> None:
        wf = _make_workflow(db)
        await db.commit()

        r = await api_client.get(f"/workflows/{wf.id}/executions")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["size"] == 20

    async def test_pagination(self, api_client, db) -> None:
        wf = _make_workflow(db)
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(30):
            await _make_execution(
                db,
                wf.id,
                started_at=base + timedelta(minutes=i),
                completed_at=base + timedelta(minutes=i, seconds=2),
            )
        await db.commit()

        r = await api_client.get(
            f"/workflows/{wf.id}/executions",
            params={"size": 10, "page": 2},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 10
        assert body["total"] == 30
        assert body["page"] == 2

    async def test_ordering_recent_first(self, api_client, db) -> None:
        wf = _make_workflow(db)
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        older = await _make_execution(
            db, wf.id, started_at=base, completed_at=base + timedelta(seconds=1)
        )
        newer = await _make_execution(
            db,
            wf.id,
            started_at=base + timedelta(hours=5),
            completed_at=base + timedelta(hours=5, seconds=1),
        )
        await db.commit()

        r = await api_client.get(f"/workflows/{wf.id}/executions")
        items = r.json()["items"]
        assert items[0]["id"] == str(newer.id)
        assert items[1]["id"] == str(older.id)

    async def test_filter_by_status(self, api_client, db) -> None:
        wf = _make_workflow(db)
        await _make_execution(db, wf.id, status="COMPLETED")
        await _make_execution(db, wf.id, status="FAILED")
        await db.commit()

        r = await api_client.get(
            f"/workflows/{wf.id}/executions", params={"status": "FAILED"}
        )
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "FAILED"

    async def test_filter_status_success_maps_to_completed(self, api_client, db) -> None:
        wf = _make_workflow(db)
        await _make_execution(db, wf.id, status="COMPLETED")
        await _make_execution(db, wf.id, status="FAILED")
        await db.commit()

        r = await api_client.get(
            f"/workflows/{wf.id}/executions", params={"status": "SUCCESS"}
        )
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "COMPLETED"

    async def test_filter_by_triggered_by(self, api_client, db) -> None:
        wf = _make_workflow(db)
        await _make_execution(db, wf.id, triggered_by="cron")
        await _make_execution(db, wf.id, triggered_by="manual")
        await _make_execution(db, wf.id, triggered_by="api")
        await db.commit()

        r = await api_client.get(
            f"/workflows/{wf.id}/executions", params={"triggered_by": "cron"}
        )
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["triggered_by"] == "cron"

    async def test_filter_by_date_from(self, api_client, db) -> None:
        wf = _make_workflow(db)
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        await _make_execution(db, wf.id, started_at=base)
        await _make_execution(db, wf.id, started_at=base + timedelta(days=5))
        await db.commit()

        cutoff = (base + timedelta(days=2)).isoformat()
        r = await api_client.get(
            f"/workflows/{wf.id}/executions", params={"from": cutoff}
        )
        items = r.json()["items"]
        assert len(items) == 1

    async def test_combined_filters_and(self, api_client, db) -> None:
        wf = _make_workflow(db)
        await _make_execution(db, wf.id, status="COMPLETED", triggered_by="cron")
        await _make_execution(db, wf.id, status="FAILED", triggered_by="cron")
        await _make_execution(db, wf.id, status="COMPLETED", triggered_by="manual")
        await db.commit()

        r = await api_client.get(
            f"/workflows/{wf.id}/executions",
            params={"status": "FAILED", "triggered_by": "cron"},
        )
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "FAILED"
        assert items[0]["triggered_by"] == "cron"

    async def test_duration_ms_computed(self, api_client, db) -> None:
        wf = _make_workflow(db)
        started = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        await _make_execution(
            db,
            wf.id,
            started_at=started,
            completed_at=started + timedelta(seconds=3, milliseconds=500),
        )
        # Sem completed_at -> duration_ms deve ser None
        await _make_execution(db, wf.id, started_at=started, completed_at=None)
        await db.commit()

        r = await api_client.get(f"/workflows/{wf.id}/executions")
        items = r.json()["items"]
        durations = sorted([it["duration_ms"] for it in items], key=lambda x: (x is None, x))
        # Um com valor, outro None
        assert durations[0] == 3500
        assert durations[1] is None

    async def test_node_count_reflects_related_rows(self, api_client, db) -> None:
        wf = _make_workflow(db)
        await _make_execution(db, wf.id, node_count=5)
        await _make_execution(db, wf.id, node_count=0)
        await db.commit()

        r = await api_client.get(f"/workflows/{wf.id}/executions")
        items = r.json()["items"]
        counts = sorted([it["node_count"] for it in items])
        assert counts == [0, 5]


# ---------------------------------------------------------------------------
# Testes de DELETE
# ---------------------------------------------------------------------------

class TestDeleteExecution:
    async def test_delete_finished_execution(self, api_client, db) -> None:
        wf = _make_workflow(db)
        ex = await _make_execution(db, wf.id, status="COMPLETED", node_count=3)
        await db.commit()

        r = await api_client.delete(f"/workflows/executions/{ex.id}")
        assert r.status_code == 204

        # Cascade removeu os nodes
        remaining = await db.execute(
            __import__("sqlalchemy").select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.execution_id == ex.id
            )
        )
        assert remaining.scalars().all() == []

    async def test_delete_running_conflicts(self, api_client, db) -> None:
        wf = _make_workflow(db)
        ex = await _make_execution(db, wf.id, status="RUNNING")
        await db.commit()

        r = await api_client.delete(f"/workflows/executions/{ex.id}")
        assert r.status_code == 409
        assert "andamento" in r.json()["detail"].lower()

    async def test_delete_missing_returns_404(self, api_client) -> None:
        missing = uuid.uuid4()
        r = await api_client.delete(f"/workflows/executions/{missing}")
        assert r.status_code == 404
