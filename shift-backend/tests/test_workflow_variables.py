"""
Testes para o recurso Variaveis do Workflow.

Cobre:
- Validacao de schema (nomes duplicados, campos dependentes de tipo)
- Round-trip via endpoints PUT /workflows/{id}/variables e GET equivalente
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

# ---------------------------------------------------------------------------
# Compatibilidade Postgres -> SQLite
# ---------------------------------------------------------------------------

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "CHAR(36)"


@compiles(ARRAY, "sqlite")
def _array_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


# Imports APOS registrar os compiladores acima.
from app.api.dependencies import get_db  # noqa: E402
from app.api.v1.workflows_crud import get_workflow_variables, update_workflow_variables  # noqa: E402
from app.core.security import require_permission  # noqa: E402
from app.models.workflow import Workflow  # noqa: E402
from app.schemas.workflow import WorkflowParam, WorkflowVariablesSchema  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        # Only create the Workflow table; other models have Postgres-specific DDL
        # (e.g. '[]'::jsonb server_defaults) that SQLite cannot parse.
        await conn.run_sync(
            lambda sync_conn: Workflow.__table__.create(sync_conn, checkfirst=True)
        )
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def api_client(session_factory):
    app = FastAPI()

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

    app.add_api_route(
        "/workflows/{workflow_id}/variables",
        get_workflow_variables,
        methods=["GET"],
    )
    app.add_api_route(
        "/workflows/{workflow_id}/variables",
        update_workflow_variables,
        methods=["PUT"],
    )

    app.dependency_overrides[get_db] = _override_get_db
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


def _make_workflow(db: AsyncSession, definition: dict | None = None) -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        name="test",
        workspace_id=uuid.uuid4(),
        definition=definition or {"nodes": [], "edges": []},
    )
    db.add(wf)
    return wf


# ---------------------------------------------------------------------------
# Testes de schema (unit)
# ---------------------------------------------------------------------------

class TestWorkflowParamValidation:
    def test_connection_type_accepted_for_connection(self):
        p = WorkflowParam(name="conn", type="connection", connection_type="postgres")
        assert p.connection_type == "postgres"

    def test_connection_type_rejected_for_string(self):
        with pytest.raises(Exception, match="connection_type"):
            WorkflowParam(name="x", type="string", connection_type="postgres")

    def test_connection_type_rejected_for_secret(self):
        with pytest.raises(Exception, match="connection_type"):
            WorkflowParam(name="x", type="secret", connection_type="mysql")

    def test_accepted_extensions_accepted_for_file_upload(self):
        p = WorkflowParam(name="f", type="file_upload", accepted_extensions=[".xlsx", ".csv"])
        assert p.accepted_extensions == [".xlsx", ".csv"]

    def test_accepted_extensions_rejected_for_string(self):
        with pytest.raises(Exception, match="accepted_extensions"):
            WorkflowParam(name="x", type="string", accepted_extensions=[".csv"])

    def test_accepted_extensions_rejected_for_connection(self):
        with pytest.raises(Exception, match="accepted_extensions"):
            WorkflowParam(name="x", type="connection", accepted_extensions=[".csv"])

    def test_secret_type_no_extra_fields(self):
        p = WorkflowParam(name="api_key", type="secret")
        assert p.connection_type is None
        assert p.accepted_extensions is None

    def test_ui_order_defaults_to_zero(self):
        p = WorkflowParam(name="x", type="string")
        assert p.ui_order == 0

    def test_ui_group_accepted(self):
        p = WorkflowParam(name="x", type="string", ui_group="Configuracoes", ui_order=2)
        assert p.ui_group == "Configuracoes"
        assert p.ui_order == 2


class TestWorkflowVariablesSchema:
    def test_empty_variables_valid(self):
        schema = WorkflowVariablesSchema()
        assert schema.variables == []

    def test_unique_names_valid(self):
        schema = WorkflowVariablesSchema(variables=[
            WorkflowParam(name="conn", type="connection"),
            WorkflowParam(name="arquivo", type="file_upload"),
            WorkflowParam(name="token", type="secret"),
        ])
        assert len(schema.variables) == 3

    def test_duplicate_names_raise_error(self):
        with pytest.raises(Exception, match="duplicada"):
            WorkflowVariablesSchema(variables=[
                WorkflowParam(name="conn", type="string"),
                WorkflowParam(name="conn", type="integer"),
            ])

    def test_duplicate_names_across_types_raise_error(self):
        with pytest.raises(Exception, match="duplicada"):
            WorkflowVariablesSchema(variables=[
                WorkflowParam(name="db", type="connection"),
                WorkflowParam(name="db", type="string"),
            ])


# ---------------------------------------------------------------------------
# Testes de API (integracao)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_variables_empty(api_client, db):
    wf = _make_workflow(db)
    await db.commit()

    resp = await api_client.get(f"/workflows/{wf.id}/variables")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_variables_workflow_not_found(api_client):
    resp = await api_client.get(f"/workflows/{uuid.uuid4()}/variables")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_variables_round_trip(api_client, db):
    wf = _make_workflow(db)
    await db.commit()

    payload = {
        "variables": [
            {"name": "origem", "type": "connection", "connection_type": "postgres", "required": True},
            {"name": "arquivo", "type": "file_upload", "accepted_extensions": [".xlsx"], "required": False},
            {"name": "token_api", "type": "secret"},
        ]
    }
    put_resp = await api_client.put(f"/workflows/{wf.id}/variables", json=payload)
    assert put_resp.status_code == 200

    data = put_resp.json()
    assert len(data) == 3
    assert data[0]["name"] == "origem"
    assert data[0]["connection_type"] == "postgres"
    assert data[1]["accepted_extensions"] == [".xlsx"]
    assert data[2]["type"] == "secret"

    # Confirma persistencia via GET
    get_resp = await api_client.get(f"/workflows/{wf.id}/variables")
    assert get_resp.status_code == 200
    assert get_resp.json() == data


@pytest.mark.asyncio
async def test_put_variables_overwrites_previous(api_client, db):
    wf = _make_workflow(db)
    await db.commit()

    await api_client.put(f"/workflows/{wf.id}/variables", json={
        "variables": [{"name": "antiga", "type": "string"}]
    })
    put_resp = await api_client.put(f"/workflows/{wf.id}/variables", json={
        "variables": [{"name": "nova", "type": "integer"}]
    })
    assert put_resp.status_code == 200

    get_resp = await api_client.get(f"/workflows/{wf.id}/variables")
    names = [v["name"] for v in get_resp.json()]
    assert names == ["nova"]


@pytest.mark.asyncio
async def test_put_variables_duplicate_names_returns_422(api_client, db):
    wf = _make_workflow(db)
    await db.commit()

    resp = await api_client.put(f"/workflows/{wf.id}/variables", json={
        "variables": [
            {"name": "dup", "type": "string"},
            {"name": "dup", "type": "integer"},
        ]
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_variables_invalid_connection_type_field_returns_422(api_client, db):
    wf = _make_workflow(db)
    await db.commit()

    resp = await api_client.put(f"/workflows/{wf.id}/variables", json={
        "variables": [
            {"name": "x", "type": "string", "connection_type": "postgres"},
        ]
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_variables_workflow_not_found(api_client):
    resp = await api_client.put(f"/workflows/{uuid.uuid4()}/variables", json={"variables": []})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_variables_clears_list(api_client, db):
    wf = _make_workflow(db)
    await db.commit()

    await api_client.put(f"/workflows/{wf.id}/variables", json={
        "variables": [{"name": "x", "type": "string"}]
    })
    put_resp = await api_client.put(f"/workflows/{wf.id}/variables", json={"variables": []})
    assert put_resp.status_code == 200
    assert put_resp.json() == []

    get_resp = await api_client.get(f"/workflows/{wf.id}/variables")
    assert get_resp.json() == []
