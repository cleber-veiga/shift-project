"""
Testes dos endpoints de export/import de workflows (Fase 9).

Padrao identico ao test_workflow_executions_api.py — mini-app FastAPI com
SQLite in-memory e bypass de require_permission.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

import pytest_asyncio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "CHAR(36)"


@compiles(ARRAY, "sqlite")
def _array_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    # SQLite nao tem ARRAY nativo; armazenamos como JSON em testes.
    return "JSON"


from app.api.dependencies import get_db  # noqa: E402
from app.api.v1.workflow_export import (  # noqa: E402
    export_workflow,
    import_workflow,
)
from app.db.base import Base  # noqa: E402
from app.models.workflow import Workflow  # noqa: E402


# SQLite nao executa server_defaults Postgres-only (gen_random_uuid). Em
# producao o banco gera o UUID; aqui delegamos para Python antes do insert.
@pytest.fixture(autouse=True)
def _patch_workflow_id_default():
    from sqlalchemy import event

    def _set_id(mapper, connection, target):  # type: ignore[no-untyped-def]
        if target.id is None:
            target.id = uuid.uuid4()

    event.listen(Workflow, "before_insert", _set_id)
    try:
        yield
    finally:
        event.remove(Workflow, "before_insert", _set_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sqlite_compatible_metadata():
    """Cria copia da metadata sem defaults postgres-especificos.

    A definition do Workflow model usa ``text(\"'[]'::jsonb\")`` e
    ``text(\"gen_random_uuid()\")`` como server_defaults; em SQLite isso
    quebra create_all. Aqui clonamos so as tabelas que importam para o
    teste (workflows + dependencias) e zeramos os server_defaults.
    """
    from sqlalchemy import MetaData

    from sqlalchemy import Table

    needed = {"workflows", "workspaces", "projects", "organizations"}
    md = MetaData()
    for name, table in Base.metadata.tables.items():
        if name not in needed:
            continue
        new_cols = []
        for col in table.columns:
            new_col = col._copy()
            # Strip apenas defaults com sintaxe postgres-only (jsonb casts,
            # gen_random_uuid). Defaults seguros (CURRENT_TIMESTAMP, '0',
            # 'draft') sao preservados.
            sd = new_col.server_default
            if sd is not None:
                sql = str(getattr(sd, "arg", sd)).lower()
                # Defaults postgres-only (jsonb cast, gen_random_uuid) sao
                # invalidos em SQLite — removemos para a metadata local.
                # Para colunas chave (id), o evento before_insert fixture
                # ``_patch_workflow_id_default`` cuida do default Python.
                if "::jsonb" in sql or "::json" in sql or "gen_random_uuid" in sql:
                    new_col.server_default = None
            new_cols.append(new_col)
        Table(
            name, md, *new_cols,
            *[c._copy() for c in table.constraints
              if c.__class__.__name__ in {"PrimaryKeyConstraint", "UniqueConstraint", "CheckConstraint"}],
        )
    return md


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    md = _sqlite_compatible_metadata()
    async with eng.begin() as conn:
        await conn.run_sync(md.create_all)
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
        "/workflows/{workflow_id}/export",
        export_workflow,
        methods=["POST"],
    )
    app.add_api_route(
        "/workflows/import",
        import_workflow,
        methods=["POST"],
        status_code=201,
    )

    app.dependency_overrides[get_db] = _override_get_db
    for route in app.router.routes:
        if hasattr(route, "dependant"):
            for sub in route.dependant.dependencies:
                if sub.call is not None and getattr(sub.call, "__qualname__", "").startswith(
                    "require_permission"
                ):
                    app.dependency_overrides[sub.call] = _allow

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_supported_definition() -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "inline_data", "position": {"x": 0, "y": 0},
             "data": {"type": "inline_data", "data": [{"a": 1}]}},
            {"id": "f", "type": "filter", "position": {"x": 100, "y": 0},
             "data": {
                 "type": "filter",
                 "conditions": [{"field": "a", "operator": "gt", "value": 0}],
                 "logic": "and",
             }},
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "f"},
        ],
    }


def _make_unsupported_definition() -> dict:
    base = _make_supported_definition()
    base["nodes"].append({
        "id": "ai",
        "type": "code",
        "position": {"x": 200, "y": 0},
        "data": {"type": "code", "code": "x = 1"},
    })
    base["edges"].append({"id": "e2", "source": "f", "target": "ai"})
    return base


async def _make_workflow(db: AsyncSession, *, definition: dict, name: str = "demo") -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        name=name,
        workspace_id=uuid.uuid4(),
        definition=definition,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExportEndpoint:
    @pytest.mark.parametrize("fmt,content_keyword,content_type", [
        ("sql", "CREATE OR REPLACE TEMPORARY TABLE", "text/plain"),
        ("python", "import duckdb", "text/x-python"),
        ("yaml", "shift_version", "application/x-yaml"),
    ])
    async def test_export_returns_correct_content(self, api_client, db, fmt, content_keyword, content_type):
        wf = await _make_workflow(db, definition=_make_supported_definition())
        r = await api_client.post(f"/workflows/{wf.id}/export?format={fmt}")
        assert r.status_code == 200, r.text
        assert content_type in r.headers["content-type"]
        assert content_keyword in r.text
        assert 'attachment; filename="' in r.headers.get("content-disposition", "")

    async def test_export_unsupported_returns_422_with_structured_body(self, api_client, db):
        wf = await _make_workflow(db, definition=_make_unsupported_definition())
        r = await api_client.post(f"/workflows/{wf.id}/export?format=sql")
        assert r.status_code == 422
        body = r.json()
        # FastAPI envelopa em {"detail": ...} quando HTTPException(detail=...)
        detail = body["detail"]
        assert "unsupported" in detail
        assert detail["unsupported"][0]["node_type"] == "code"
        assert detail["unsupported"][0]["reason"]

    async def test_export_unknown_workflow_returns_404(self, api_client):
        fake = uuid.uuid4()
        r = await api_client.post(f"/workflows/{fake}/export?format=sql")
        assert r.status_code == 404

    async def test_export_invalid_format_returns_422(self, api_client, db):
        wf = await _make_workflow(db, definition=_make_supported_definition())
        r = await api_client.post(f"/workflows/{wf.id}/export?format=xml")
        # Query Literal validation -> 422 (FastAPI default).
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class TestImportEndpoint:
    async def test_import_yaml_creates_workflow(self, api_client, db):
        # Gera um YAML valido a partir de uma definition reutilizando to_yaml.
        from app.services.workflow.serializers import to_yaml
        yaml_text = to_yaml(
            _make_supported_definition(),
            name="from_yaml_demo",
            workflow_id="ignored-in-import",
        )

        ws = uuid.uuid4()
        files = {"file": ("flow.yaml", yaml_text.encode("utf-8"), "application/x-yaml")}
        r = await api_client.post(f"/workflows/import?workspace_id={ws}", files=files)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "from_yaml_demo"
        assert body["definition"]["nodes"][0]["id"] == "src"
        # workflow_id do payload e descartado — o backend gera UUID novo.
        assert body["id"] != "ignored-in-import"

    async def test_import_invalid_extension_returns_400(self, api_client):
        ws = uuid.uuid4()
        files = {"file": ("flow.txt", b"shift_version: '1.0'\nnodes: []\nedges: []\n", "text/plain")}
        r = await api_client.post(f"/workflows/import?workspace_id={ws}", files=files)
        assert r.status_code == 400
        assert ".yaml" in r.json()["detail"]

    async def test_import_missing_version_returns_400(self, api_client):
        ws = uuid.uuid4()
        bad = b"nodes: []\nedges: []\n"
        files = {"file": ("flow.yaml", bad, "application/x-yaml")}
        r = await api_client.post(f"/workflows/import?workspace_id={ws}", files=files)
        assert r.status_code == 400
        detail = r.json()["detail"]
        # YamlVersionError -> dict
        assert isinstance(detail, dict)
        assert detail.get("found_version") is None
        assert detail.get("expected_version") == "1.0"

    async def test_import_missing_workspace_and_project_returns_422(self, api_client):
        from app.services.workflow.serializers import to_yaml
        yaml_text = to_yaml(_make_supported_definition(), name="x", workflow_id="x")
        files = {"file": ("flow.yaml", yaml_text.encode("utf-8"), "application/x-yaml")}
        r = await api_client.post("/workflows/import", files=files)
        assert r.status_code == 422
        assert "projeto" in r.json()["detail"] or "workspace" in r.json()["detail"]

    async def test_import_malformed_yaml_returns_400(self, api_client):
        ws = uuid.uuid4()
        files = {"file": ("flow.yaml", b"shift_version: 1.0\nnodes: [unclosed", "application/x-yaml")}
        r = await api_client.post(f"/workflows/import?workspace_id={ws}", files=files)
        assert r.status_code == 400
