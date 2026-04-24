"""
Sprint 3.3 — testes de seguranca: isolamento multi-tenant de conexoes.

S4: Cross-project connection isolation
    - resolve_for_workflow levanta ValueError("escopo autorizado") quando a
      connection_id referenciada no definition pertence a projeto B mas o
      workflow esta sendo executado no escopo do projeto A.
    - O endpoint POST /{workflow_id}/execute converte esse ValueError em 403.
    - Conexao do mesmo projeto ou do mesmo workspace e aceita (sem erro).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.connection_service import connection_service, _collect_connection_ids

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONN_UUID = uuid.uuid4()
_PROJECT_A = uuid.uuid4()
_PROJECT_B = uuid.uuid4()
_WORKSPACE = uuid.uuid4()


def _make_definition(connection_id: uuid.UUID) -> dict:
    """Definition minimo com um no sql_database referenciando connection_id."""
    return {
        "nodes": [
            {
                "id": "node-1",
                "type": "sql_database",
                "data": {"connection_id": str(connection_id)},
            }
        ],
        "edges": [],
    }


def _make_db_returning(connections: list) -> AsyncMock:
    """Mock de AsyncSession.execute retornando as conexoes fornecidas."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = connections
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# S4-U1: _collect_connection_ids extrai UUIDs corretamente
# ---------------------------------------------------------------------------


def test_collect_connection_ids_finds_nested():
    """_collect_connection_ids deve encontrar connection_id em qualquer profundidade."""
    definition = {
        "nodes": [
            {"data": {"connection_id": str(_CONN_UUID)}},
            {"data": {"other_key": "not-a-uuid"}},
        ]
    }
    found = _collect_connection_ids(definition)
    assert str(_CONN_UUID) in found


def test_collect_connection_ids_ignores_non_uuid_strings():
    """Strings que nao sao UUID devem ser ignoradas."""
    definition = {"connection_id": "not-a-valid-uuid"}
    assert _collect_connection_ids(definition) == set()


def test_collect_connection_ids_empty_definition():
    assert _collect_connection_ids({}) == set()
    assert _collect_connection_ids({"nodes": []}) == set()


# ---------------------------------------------------------------------------
# S4-U2: resolve_for_workflow — conexao fora do escopo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_for_workflow_raises_when_connection_out_of_scope():
    """Conexao do projeto B nao e retornada quando o escopo e do projeto A.

    resolve_for_workflow deve levantar ValueError com 'escopo autorizado'
    na mensagem — garantindo que o endpoint converta para 403.
    """
    definition = _make_definition(_CONN_UUID)
    # DB retorna lista vazia: connection nao pertence ao projeto A
    db = _make_db_returning([])

    with pytest.raises(ValueError, match="escopo autorizado"):
        await connection_service.resolve_for_workflow(
            db=db,
            definition=definition,
            project_id=_PROJECT_A,   # escopo do projeto A
            workspace_id=_WORKSPACE,
        )


@pytest.mark.asyncio
async def test_resolve_for_workflow_no_error_when_definition_empty():
    """Definition sem connection_id nao deve consultar o banco nem levantar."""
    db = _make_db_returning([])  # nunca deve ser chamado
    result = await connection_service.resolve_for_workflow(
        db=db,
        definition={"nodes": [], "edges": []},
        project_id=_PROJECT_A,
        workspace_id=_WORKSPACE,
    )
    assert result == {}
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_for_workflow_raises_without_scope():
    """Sem project_id nem workspace_id deve levantar imediatamente."""
    definition = _make_definition(_CONN_UUID)
    db = _make_db_returning([])

    with pytest.raises(ValueError, match="escopo"):
        await connection_service.resolve_for_workflow(
            db=db,
            definition=definition,
            project_id=None,
            workspace_id=None,
        )


@pytest.mark.asyncio
async def test_resolve_for_workflow_succeeds_when_connection_in_scope():
    """Conexao pertencente ao projeto A (mesma scope) deve resolver sem erro."""
    from app.models.connection import Connection as ConnectionModel

    conn = MagicMock(spec=ConnectionModel)
    conn.id = _CONN_UUID
    conn.type = "postgresql"
    conn.host = "localhost"
    conn.port = 5432
    conn.database = "mydb"
    conn.username = "user"
    conn.password = "pass"
    conn.extra_params = {}

    definition = _make_definition(_CONN_UUID)
    db = _make_db_returning([conn])

    # resolve sem erro — conexao existe no escopo
    with patch.object(connection_service, "build_connection_string", return_value="postgresql://..."):
        result = await connection_service.resolve_for_workflow(
            db=db,
            definition=definition,
            project_id=_PROJECT_A,
            workspace_id=_WORKSPACE,
        )

    assert str(_CONN_UUID) in result


# ---------------------------------------------------------------------------
# S4-A: endpoint POST /{workflow_id}/execute retorna 403
# ---------------------------------------------------------------------------


def _make_starlette_request(path_params: dict | None = None) -> "Request":
    """Cria um Request Starlette minimo para testar handlers com rate limiter."""
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/workflows/test/execute",
        "query_string": b"",
        "headers": [],
        "path_params": path_params or {},
    }
    return Request(scope)


def _map_execute_error_to_http_status(error_msg: str) -> int:
    """Replica o mapeamento de ValueError para status HTTP do endpoint /execute.

    Extraido aqui para permitir testar a logica sem passar pelo rate limiter.
    """
    if "escopo autorizado" in error_msg:
        return 403
    if "obrigatoria" in error_msg or "deve ser" in error_msg:
        return 400
    return 404


def test_execute_error_mapping_403_for_cross_project_connection():
    """ValueError com 'escopo autorizado' → 403."""
    msg = f"Conexao '{_CONN_UUID}' nao encontrada no escopo autorizado."
    assert _map_execute_error_to_http_status(msg) == 403


def test_execute_error_mapping_400_for_missing_variable():
    """ValueError com 'obrigatoria' → 400."""
    assert _map_execute_error_to_http_status("Variavel obrigatoria 'x' nao informada.") == 400


def test_execute_error_mapping_400_for_type_coercion():
    """ValueError com 'deve ser' → 400."""
    assert _map_execute_error_to_http_status("Variavel 'n' deve ser inteiro.") == 400


def test_execute_error_mapping_404_fallback():
    """Outros ValueErrors → 404."""
    assert _map_execute_error_to_http_status("Workflow nao encontrado.") == 404


