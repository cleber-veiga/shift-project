"""
Testes do no sql_script.

Usa SQLite em memoria (ou em arquivo temporario) como banco alvo — segue
o padrao de test_composite_insert_node.py. A origem para o modo
``execute_many`` continua sendo DuckDB, mesmo contrato dos demais nos
de carga do Shift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest
import sqlalchemy as sa

from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.nodes.sql_script import SqlScriptProcessor
from tests.conftest import create_duckdb_with_rows, make_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dest_sqlite(tmp_path: Path) -> str:
    """SQLite com tabela CLIENTE populada, retorna a connection string."""
    db_file = tmp_path / "script.sqlite"
    cs = f"sqlite:///{db_file}"
    engine = sa.create_engine(cs)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE CLIENTE (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cnpj VARCHAR(20) NOT NULL,
                    nome VARCHAR(100) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO CLIENTE (cnpj, nome) VALUES "
                "('00000000000100', 'ALFA'), "
                "('00000000000200', 'BETA')"
            )
        )
    engine.dispose()
    return cs


def _count(connection_string: str, table: str) -> int:
    engine = sa.create_engine(connection_string)
    try:
        with engine.connect() as conn:
            return (
                conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()
                or 0
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Modo "query"
# ---------------------------------------------------------------------------


class TestQueryMode:
    def test_query_mode_returns_rows(
        self, tmp_path: Path, dest_sqlite: str
    ) -> None:
        # Contexto com um no upstream que expoe o cnpj alvo como campo.
        context: dict[str, Any] = {
            "execution_id": "exec-q",
            "workflow_id": "wf-q",
            "upstream_results": {
                "prev": {
                    "node_id": "prev",
                    "status": "completed",
                    "cnpj": "00000000000100",
                }
            },
        }

        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-q",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT id, cnpj, nome FROM CLIENTE WHERE cnpj = :cnpj",
                "parameters": {"cnpj": "upstream.prev.cnpj"},
                "mode": "query",
                "output_schema": [
                    {"name": "id", "type": "BIGINT"},
                    {"name": "cnpj", "type": "VARCHAR"},
                    {"name": "nome", "type": "VARCHAR"},
                ],
            },
            context,
        )

        assert output["status"] == "completed"
        assert output["row_count"] == 1
        payload = output["sql_result"]
        reference = payload["reference"]
        assert reference["storage_type"] == "duckdb"

        # DuckDB materializado e legivel pelo downstream.
        conn = duckdb.connect(reference["database_path"], read_only=True)
        try:
            rows = conn.execute(
                f'SELECT cnpj, nome FROM main."{reference["table_name"]}"'
            ).fetchall()
        finally:
            conn.close()

        assert rows == [("00000000000100", "ALFA")]


# ---------------------------------------------------------------------------
# Modo "execute"
# ---------------------------------------------------------------------------


class TestExecuteMode:
    def test_execute_mode_insert(
        self, tmp_path: Path, dest_sqlite: str
    ) -> None:
        context: dict[str, Any] = {
            "execution_id": "exec-e",
            "workflow_id": "wf-e",
            "upstream_results": {
                "prev": {
                    "node_id": "prev",
                    "status": "completed",
                    "cnpj": "00000000000999",
                    "nome": "GAMA",
                }
            },
        }

        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-e",
            {
                "connection_string": dest_sqlite,
                "script": (
                    "INSERT INTO CLIENTE (cnpj, nome) VALUES (:cnpj, :nome)"
                ),
                "parameters": {
                    "cnpj": "upstream.prev.cnpj",
                    "nome": "upstream.prev.nome",
                },
                "mode": "execute",
            },
            context,
        )

        assert output["status"] == "completed"
        assert output["rows_affected"] == 1
        assert _count(dest_sqlite, "CLIENTE") == 3


# ---------------------------------------------------------------------------
# Modo "execute_many"
# ---------------------------------------------------------------------------


class TestExecuteManyMode:
    def test_execute_many_iterates_upstream(
        self, tmp_path: Path, dest_sqlite: str
    ) -> None:
        source_rows = [
            {"CNPJ_SRC": "000001", "NOME_SRC": "UM"},
            {"CNPJ_SRC": "000002", "NOME_SRC": "DOIS"},
            {"CNPJ_SRC": "000003", "NOME_SRC": "TRES"},
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)
        context = make_context(db_path, "src")

        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-em",
            {
                "connection_string": dest_sqlite,
                "script": (
                    "INSERT INTO CLIENTE (cnpj, nome) VALUES (:cnpj, :nome)"
                ),
                "parameters": {"cnpj": "CNPJ_SRC", "nome": "NOME_SRC"},
                "mode": "execute_many",
            },
            context,
        )

        assert output["status"] == "completed"
        assert output["rows_affected"] == 3
        assert output["rows_processed"] == 3
        # Ja havia 2 linhas (ALFA, BETA) + 3 inseridas.
        assert _count(dest_sqlite, "CLIENTE") == 5


# ---------------------------------------------------------------------------
# Validacoes e seguranca
# ---------------------------------------------------------------------------


class TestValidation:
    def test_rejects_string_interpolation(self, dest_sqlite: str) -> None:
        processor = SqlScriptProcessor()
        with pytest.raises(NodeProcessingError, match="interpolacao"):
            processor.process(
                "sqlscript-bad",
                {
                    "connection_string": dest_sqlite,
                    # `{cnpj}` ≠ `:cnpj` — interpolacao proibida.
                    "script": "SELECT * FROM CLIENTE WHERE cnpj = '{cnpj}'",
                    "parameters": {"cnpj": "upstream.prev.cnpj"},
                    "mode": "query",
                },
                {"upstream_results": {"prev": {"cnpj": "X"}}},
            )

    def test_timeout_enforced(self, dest_sqlite: str) -> None:
        # CTE recursivo propositalmente grande — excede timeout de 1s.
        slow_script = (
            "WITH RECURSIVE nums(n) AS ("
            "  SELECT 1 UNION ALL SELECT n + 1 FROM nums WHERE n < 100000000"
            ") SELECT COUNT(*) AS total FROM nums"
        )
        processor = SqlScriptProcessor()
        with pytest.raises(NodeProcessingError, match="timeout"):
            processor.process(
                "sqlscript-timeout",
                {
                    "connection_string": dest_sqlite,
                    "script": slow_script,
                    "mode": "query",
                    "timeout_seconds": 1,
                },
                {"upstream_results": {}},
            )

    def test_invalid_connection_id(self) -> None:
        processor = SqlScriptProcessor()
        # connection_string ausente (nao foi injetada pelo runner).
        with pytest.raises(NodeProcessingError, match="connection_string"):
            processor.process(
                "sqlscript-no-conn",
                {
                    "script": "SELECT 1",
                    "mode": "query",
                },
                {"upstream_results": {}},
            )

    def test_missing_script(self, dest_sqlite: str) -> None:
        processor = SqlScriptProcessor()
        with pytest.raises(NodeProcessingError, match="script"):
            processor.process(
                "sqlscript-empty",
                {
                    "connection_string": dest_sqlite,
                    "script": "   ",
                    "mode": "query",
                },
                {"upstream_results": {}},
            )

    def test_invalid_mode(self, dest_sqlite: str) -> None:
        processor = SqlScriptProcessor()
        with pytest.raises(NodeProcessingError, match="modo invalido"):
            processor.process(
                "sqlscript-mode",
                {
                    "connection_string": dest_sqlite,
                    "script": "SELECT 1",
                    "mode": "bogus",
                },
                {"upstream_results": {}},
            )

    def test_output_schema_mismatch(self, dest_sqlite: str) -> None:
        processor = SqlScriptProcessor()
        with pytest.raises(NodeProcessingError, match="output_schema"):
            processor.process(
                "sqlscript-schema",
                {
                    "connection_string": dest_sqlite,
                    "script": "SELECT id, cnpj FROM CLIENTE",
                    "mode": "query",
                    "output_schema": [
                        {"name": "id", "type": "BIGINT"},
                        # Coluna declarada que nao existe no retorno.
                        {"name": "nome_errado", "type": "VARCHAR"},
                    ],
                },
                {"upstream_results": {}},
            )

    def test_sql_error_raises_node_processing_error(
        self, dest_sqlite: str
    ) -> None:
        processor = SqlScriptProcessor()
        with pytest.raises(NodeProcessingError, match="falha ao executar"):
            processor.process(
                "sqlscript-sql-err",
                {
                    "connection_string": dest_sqlite,
                    "script": "SELECT * FROM TABELA_INEXISTENTE",
                    "mode": "query",
                },
                {"upstream_results": {}},
            )


# ---------------------------------------------------------------------------
# Resolução de parâmetros — formato ParameterValue
# ---------------------------------------------------------------------------


class TestParameterValueResolution:
    """Garante que os modos de parâmetro legado e novo funcionam juntos."""

    def _context(self) -> dict:
        return {
            "execution_id": "exec-pv",
            "workflow_id": "wf-pv",
            "input_data": {"campo_input": "VALOR_INPUT"},
            "vars": {"ESTAB": "0001"},
            "upstream_results": {
                "node_prev": {
                    "node_id": "node_prev",
                    "status": "completed",
                    "IDITEM": "ABC123",
                    "ESTAB": "0002",
                    "data": {"campo_aninhado": "ANINHADO"},
                }
            },
        }

    def test_legacy_string_upstream_results(self, dest_sqlite: str) -> None:
        """Formato legado 'upstream_results.node_X.CAMPO' continua funcionando."""
        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-legacy",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT id FROM CLIENTE WHERE id = :id",
                "parameters": {
                    # Legacy dotted path
                    "id": "upstream_results.node_prev.IDITEM",
                },
                "mode": "execute",
            },
            {
                **self._context(),
                "upstream_results": {
                    "node_prev": {
                        "node_id": "node_prev",
                        "status": "completed",
                        "IDITEM": 1,
                    }
                },
            },
        )
        assert output["status"] == "completed"

    def test_legacy_string_upstream_alias(self, dest_sqlite: str) -> None:
        """Alias 'upstream.node_X.CAMPO' também é aceito."""
        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-alias",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT COUNT(*) FROM CLIENTE WHERE cnpj = :cnpj",
                "parameters": {"cnpj": "upstream.node_prev.IDITEM"},
                "mode": "execute",
            },
            {
                **self._context(),
                "upstream_results": {
                    "node_prev": {
                        "node_id": "node_prev",
                        "status": "completed",
                        "IDITEM": "00000000000100",
                    }
                },
            },
        )
        assert output["status"] == "completed"

    def test_new_fixed_parameter(self, dest_sqlite: str) -> None:
        """Novo formato ParameterValue fixo — value literal."""
        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-fixed",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT COUNT(*) FROM CLIENTE WHERE cnpj = :cnpj",
                "parameters": {
                    "cnpj": {"mode": "fixed", "value": "00000000000100"},
                },
                "mode": "execute",
            },
            self._context(),
        )
        assert output["status"] == "completed"

    def test_new_dynamic_single_token(self, dest_sqlite: str) -> None:
        """Novo formato ParameterValue dynamic — token único {{node.campo}}."""
        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-dyn-single",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT COUNT(*) FROM CLIENTE WHERE cnpj = :cnpj",
                "parameters": {
                    "cnpj": {
                        "mode": "dynamic",
                        "template": "{{node_prev.IDITEM}}",
                    },
                },
                "mode": "execute",
            },
            {
                **self._context(),
                "upstream_results": {
                    "node_prev": {
                        "node_id": "node_prev",
                        "status": "completed",
                        "IDITEM": "00000000000100",
                    }
                },
            },
        )
        assert output["status"] == "completed"

    def test_new_dynamic_nested_path(self, dest_sqlite: str) -> None:
        """Token multi-segmento {{node.data.campo}} percorre aninhamento."""
        processor = SqlScriptProcessor()
        context = self._context()
        output = processor.process(
            "sqlscript-nested",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT COUNT(*) FROM CLIENTE WHERE cnpj = :cnpj",
                "parameters": {
                    "cnpj": {
                        "mode": "dynamic",
                        "template": "{{node_prev.data.campo_aninhado}}",
                    },
                },
                "mode": "execute",
            },
            context,
        )
        assert output["status"] == "completed"

    def test_new_dynamic_vars(self, dest_sqlite: str) -> None:
        """Token {{vars.X}} resolve via ctx.vars."""
        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-vars",
            {
                "connection_string": dest_sqlite,
                "script": "SELECT COUNT(*) FROM CLIENTE WHERE cnpj = :cnpj",
                "parameters": {
                    "cnpj": {
                        "mode": "dynamic",
                        "template": "{{vars.ESTAB}}",
                    },
                },
                "mode": "execute",
            },
            self._context(),
        )
        assert output["status"] == "completed"

    def test_execute_many_accepts_fixed_pv(
        self, tmp_path: Path, dest_sqlite: str
    ) -> None:
        """execute_many aceita ParameterValue fixed (novo formato) como nome de coluna."""
        source_rows = [{"CNPJ_COL": "000099", "NOME_COL": "DELTA"}]
        db_path = tmp_path / "src2.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)
        context = make_context(db_path, "src")

        processor = SqlScriptProcessor()
        output = processor.process(
            "sqlscript-em-pv",
            {
                "connection_string": dest_sqlite,
                "script": "INSERT INTO CLIENTE (cnpj, nome) VALUES (:cnpj, :nome)",
                "parameters": {
                    "cnpj": {"mode": "fixed", "value": "CNPJ_COL"},
                    "nome": {"mode": "fixed", "value": "NOME_COL"},
                },
                "mode": "execute_many",
            },
            context,
        )
        assert output["status"] == "completed"
        assert output["rows_affected"] == 1
