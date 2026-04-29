"""
Testes do endpoint GET /executions/{id}/nodes/{id}/preview.

Foco principal: regressão do bug "Nenhuma tabela encontrada no resultado do nó"
quando o caminho legacy do extractor (extract_sql_to_duckdb com dlt) materializa
em schema ``shift_extract`` em vez de ``main``. O endpoint precisa:
  - Achar tabelas em qualquer schema não-sistema via information_schema.
  - Ignorar tabelas internas do dlt (``_dlt_*``).
  - Retornar 404 só quando não houver dado de usuário.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import duckdb
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import executions as executions_module
from app.api.v1.executions import get_node_preview
from app.data_pipelines.duckdb_storage import sanitize_name


_EXECUTION_ID = "11111111-1111-1111-1111-111111111111"
_NODE_ID = "node_test_42"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def execution_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Aponta o endpoint para um diretório temporário e cria a pasta da execução.

    O endpoint resolve o path do banco como
    ``_SHIFT_EXECUTIONS_DIR / execution_id / sanitize_name(node_id).duckdb``;
    monkeypatch garante que o teste não toque ``/tmp/shift/executions``.
    """
    base = tmp_path / "shift_executions"
    exec_dir = base / _EXECUTION_ID
    exec_dir.mkdir(parents=True)
    monkeypatch.setattr(executions_module, "_SHIFT_EXECUTIONS_DIR", base)
    return exec_dir


@pytest.fixture
def db_path(execution_dir: Path) -> Path:
    """Caminho do DuckDB para o nó de teste — nome sanitizado pelo endpoint."""
    return execution_dir / f"{sanitize_name(_NODE_ID)}.duckdb"


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    """Mini-app FastAPI com require_permission bypassado."""
    app = FastAPI()

    async def _allow() -> None:
        return None

    app.add_api_route(
        "/executions/{execution_id}/nodes/{node_id}/preview",
        get_node_preview,
        methods=["GET"],
    )

    for route in app.router.routes:
        if not hasattr(route, "dependant"):
            continue
        for sub in route.dependant.dependencies:
            if sub.call is None:
                continue
            if getattr(sub.call, "__qualname__", "").startswith("require_permission"):
                app.dependency_overrides[sub.call] = _allow

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _create_db(db_path: Path, sql: str) -> None:
    """Cria o arquivo DuckDB e roda DDL/DML inicial."""
    conn = duckdb.connect(str(db_path))
    try:
        for stmt in [s for s in sql.split(";") if s.strip()]:
            conn.execute(stmt)
    finally:
        conn.close()


def _preview_url(execution_id: str = _EXECUTION_ID, node_id: str = _NODE_ID) -> str:
    return f"/executions/{execution_id}/nodes/{node_id}/preview"


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------

class TestPreviewSchemaResolution:

    @pytest.mark.asyncio
    async def test_table_in_main_schema_returns_rows(
        self, api_client: AsyncClient, db_path: Path
    ) -> None:
        # Caminho particionado do extractor materializa em main; valida que o
        # comportamento atual (caso feliz) não regrediu.
        _create_db(db_path, "CREATE TABLE main.results AS SELECT 1 AS x")

        resp = await api_client.get(_preview_url())

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["row_count"] == 1
        assert body["total_rows"] == 1
        assert body["columns"] == ["x"]
        assert body["rows"] == [{"x": 1}]

    @pytest.mark.asyncio
    async def test_table_in_shift_extract_schema_returns_rows(
        self, api_client: AsyncClient, db_path: Path
    ) -> None:
        # Regressão direta do bug: caminho legacy via dlt cria a tabela
        # dentro do schema shift_extract. Antes do fix, o endpoint usava
        # SHOW TABLES (só main) e devolvia 404 mesmo com dado válido.
        _create_db(
            db_path,
            """
            CREATE SCHEMA shift_extract;
            CREATE TABLE shift_extract.orders AS SELECT 1 AS id;
            """,
        )

        resp = await api_client.get(_preview_url())

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["row_count"] == 1
        assert body["total_rows"] == 1
        assert body["columns"] == ["id"]
        assert body["rows"] == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_dlt_internal_tables_are_filtered(
        self, api_client: AsyncClient, db_path: Path
    ) -> None:
        # dlt cria _dlt_loads, _dlt_pipeline_state, _dlt_version no mesmo
        # schema. Sem o filtro `_dlt_*` o preview poderia mostrar uma dessas.
        _create_db(
            db_path,
            """
            CREATE SCHEMA shift_extract;
            CREATE TABLE shift_extract._dlt_loads (load_id VARCHAR);
            CREATE TABLE shift_extract._dlt_version (version VARCHAR);
            CREATE TABLE shift_extract.orders AS SELECT 42 AS id;
            INSERT INTO shift_extract._dlt_loads VALUES ('xyz');
            """,
        )

        resp = await api_client.get(_preview_url())

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["columns"] == ["id"]
        assert body["rows"] == [{"id": 42}]

    @pytest.mark.asyncio
    async def test_empty_database_returns_404(
        self, api_client: AsyncClient, db_path: Path
    ) -> None:
        # Banco existe (foi tocado por algum motivo) mas não tem nenhuma
        # tabela base — preview deve dar 404 com mensagem clara.
        _create_db(db_path, "CREATE SCHEMA empty_marker")

        resp = await api_client.get(_preview_url())

        assert resp.status_code == 404
        assert "Nenhuma tabela encontrada" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_only_dlt_internal_tables_returns_404(
        self, api_client: AsyncClient, db_path: Path
    ) -> None:
        # Caso degenerado: dlt rodou mas o resource não escreveu nenhuma
        # linha; só sobrou metadata. Sem dado de usuário, preview = 404.
        _create_db(
            db_path,
            """
            CREATE SCHEMA shift_extract;
            CREATE TABLE shift_extract._dlt_loads (load_id VARCHAR);
            CREATE TABLE shift_extract._dlt_version (version VARCHAR);
            """,
        )

        resp = await api_client.get(_preview_url())

        assert resp.status_code == 404
        assert "Nenhuma tabela encontrada" in resp.json()["detail"]
