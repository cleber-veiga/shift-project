"""
Testes de integracao do no ``composite_insert``.

Usa SQLite como banco de destino (suporta RETURNING desde 3.35) para
validar o fluxo real: INSERT multi-tabela em transacao unica com
propagacao de FKs via RETURNING, e rollback quando um passo falha.

A origem das linhas continua sendo DuckDB (mesmo contrato dos demais
nos de carga do Shift).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.services.load_service import load_service
from app.services.workflow.nodes.composite_insert import CompositeInsertProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import create_duckdb_with_rows, make_context


# ---------------------------------------------------------------------------
# Fixtures: banco SQLite de destino com as 3 tabelas da "nota"
# ---------------------------------------------------------------------------

@pytest.fixture
def dest_sqlite(tmp_path: Path) -> str:
    """Cria um SQLite com NOTA + NOTAITEM + NOTAICMS e devolve a connection string."""
    db_file = tmp_path / "dest.sqlite"
    cs = f"sqlite:///{db_file}"
    engine = sa.create_engine(cs)
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE NOTA (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero VARCHAR(50) NOT NULL,
                cliente_id INTEGER NOT NULL
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE NOTAITEM (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nota_id INTEGER NOT NULL,
                produto VARCHAR(100) NOT NULL,
                quantidade INTEGER NOT NULL
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE NOTAICMS (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notaitem_id INTEGER NOT NULL,
                aliquota DOUBLE NOT NULL
            )
        """))
    engine.dispose()
    return cs


@pytest.fixture
def blueprint_nota() -> dict[str, Any]:
    """Blueprint classico: NOTA -> NOTAITEM -> NOTAICMS, tudo 1-1-1."""
    return {
        "tables": [
            {
                "alias": "nota",
                "table": "NOTA",
                "role": "header",
                "columns": ["numero", "cliente_id"],
                "returning": ["id"],
            },
            {
                "alias": "item",
                "table": "NOTAITEM",
                "role": "child",
                "parent_alias": "nota",
                "fk_map": [{"child_column": "nota_id", "parent_returning": "id"}],
                "columns": ["produto", "quantidade"],
                "returning": ["id"],
            },
            {
                "alias": "icms",
                "table": "NOTAICMS",
                "role": "child",
                "parent_alias": "item",
                "fk_map": [{"child_column": "notaitem_id", "parent_returning": "id"}],
                "columns": ["aliquota"],
                "returning": [],
            },
        ]
    }


@pytest.fixture
def field_mapping_nota() -> dict[str, str]:
    return {
        "nota.numero": "NUMERO_NOTA",
        "nota.cliente_id": "CLIENTE_ID",
        "item.produto": "PRODUTO",
        "item.quantidade": "QUANTIDADE",
        "icms.aliquota": "ALIQUOTA",
    }


def _count(connection_string: str, table: str) -> int:
    engine = sa.create_engine(connection_string)
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Happy path: 2 linhas upstream -> 2 NOTAs + 2 NOTAITEMs + 2 NOTAICMS
# ---------------------------------------------------------------------------

class TestCompositeHappyPath:
    def test_inserts_all_three_tables_with_fk_propagation(
        self,
        tmp_path: Path,
        dest_sqlite: str,
        blueprint_nota: dict[str, Any],
        field_mapping_nota: dict[str, str],
    ) -> None:
        source_rows = [
            {
                "NUMERO_NOTA": "N001", "CLIENTE_ID": 10,
                "PRODUTO": "CADEIRA", "QUANTIDADE": 2,
                "ALIQUOTA": 18.0,
            },
            {
                "NUMERO_NOTA": "N002", "CLIENTE_ID": 20,
                "PRODUTO": "MESA", "QUANTIDADE": 1,
                "ALIQUOTA": 12.0,
            },
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)

        processor = CompositeInsertProcessor()
        config = {
            "connection_string": dest_sqlite,
            "blueprint": blueprint_nota,
            "field_mapping": field_mapping_nota,
        }
        context = make_context(db_path, "src")

        output = processor.process("comp-1", config, context)

        assert output["status"] == "success"
        assert output["rows_received"] == 2
        assert output["rows_written"] == 2

        assert _count(dest_sqlite, "NOTA") == 2
        assert _count(dest_sqlite, "NOTAITEM") == 2
        assert _count(dest_sqlite, "NOTAICMS") == 2

        # FK propagation: NOTAITEM.nota_id deve referenciar NOTA.id existentes.
        engine = sa.create_engine(dest_sqlite)
        try:
            with engine.connect() as conn:
                orphan_items = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM NOTAITEM i "
                    "WHERE NOT EXISTS (SELECT 1 FROM NOTA n WHERE n.id = i.nota_id)"
                )).scalar()
                assert orphan_items == 0

                orphan_icms = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM NOTAICMS c "
                    "WHERE NOT EXISTS (SELECT 1 FROM NOTAITEM i WHERE i.id = c.notaitem_id)"
                )).scalar()
                assert orphan_icms == 0
        finally:
            engine.dispose()

    def test_per_step_metrics_in_output(
        self,
        tmp_path: Path,
        dest_sqlite: str,
        blueprint_nota: dict[str, Any],
        field_mapping_nota: dict[str, str],
    ) -> None:
        source_rows = [
            {"NUMERO_NOTA": "X1", "CLIENTE_ID": 1,
             "PRODUTO": "P", "QUANTIDADE": 1, "ALIQUOTA": 5.0},
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)

        processor = CompositeInsertProcessor()
        output = processor.process(
            "comp-2",
            {
                "connection_string": dest_sqlite,
                "blueprint": blueprint_nota,
                "field_mapping": field_mapping_nota,
            },
            make_context(db_path, "src"),
        )

        steps = {s["alias"]: s for s in output["steps"]}
        assert steps["nota"]["rows_written"] == 1
        assert steps["item"]["rows_written"] == 1
        assert steps["icms"]["rows_written"] == 1


# ---------------------------------------------------------------------------
# Rollback: falha na 3a tabela -> tudo revertido
# ---------------------------------------------------------------------------

class TestCompositeRollback:
    def test_failure_in_third_table_rolls_back_everything(
        self,
        tmp_path: Path,
        dest_sqlite: str,
        blueprint_nota: dict[str, Any],
        field_mapping_nota: dict[str, str],
    ) -> None:
        # Linha com ALIQUOTA=None viola NOT NULL em NOTAICMS.aliquota:
        # esperamos rollback completo — 0 linhas em todas as 3 tabelas.
        source_rows = [
            {"NUMERO_NOTA": "R1", "CLIENTE_ID": 99,
             "PRODUTO": "X", "QUANTIDADE": 1, "ALIQUOTA": None},
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)

        processor = CompositeInsertProcessor()
        output = processor.process(
            "comp-rb",
            {
                "connection_string": dest_sqlite,
                "blueprint": blueprint_nota,
                "field_mapping": field_mapping_nota,
            },
            make_context(db_path, "src"),
        )

        assert output["status"] == "error"
        assert output["failed_at_alias"] == "icms"
        assert output["rows_written"] == 0

        # Rollback efetivo: nenhuma tabela foi afetada.
        assert _count(dest_sqlite, "NOTA") == 0
        assert _count(dest_sqlite, "NOTAITEM") == 0
        assert _count(dest_sqlite, "NOTAICMS") == 0

    def test_failure_in_second_row_preserves_first_row_and_reports_partial(
        self,
        tmp_path: Path,
        dest_sqlite: str,
        blueprint_nota: dict[str, Any],
        field_mapping_nota: dict[str, str],
    ) -> None:
        # Primeira linha e valida, segunda forca NOT NULL em aliquota.
        # Na fase 5c, cada linha roda em SAVEPOINT proprio: a linha 1 fica
        # persistida e a linha 2 segue para o branch on_error.
        source_rows = [
            {"NUMERO_NOTA": "OK", "CLIENTE_ID": 1,
             "PRODUTO": "A", "QUANTIDADE": 1, "ALIQUOTA": 10.0},
            {"NUMERO_NOTA": "BAD", "CLIENTE_ID": 2,
             "PRODUTO": "B", "QUANTIDADE": 1, "ALIQUOTA": None},
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)

        processor = CompositeInsertProcessor()
        output = processor.process(
            "comp-rb2",
            {
                "connection_string": dest_sqlite,
                "blueprint": blueprint_nota,
                "field_mapping": field_mapping_nota,
            },
            make_context(db_path, "src"),
        )

        assert output["status"] == "partial"
        assert output["failed_at_row_index"] == 1
        assert output["rows_written"] == 1
        assert output["succeeded_rows_count"] == 1
        assert output["failed_rows_count"] == 1
        assert set(output["active_handles"]) == {"success", "on_error"}
        assert _count(dest_sqlite, "NOTA") == 1
        assert _count(dest_sqlite, "NOTAITEM") == 1
        assert _count(dest_sqlite, "NOTAICMS") == 1


# ---------------------------------------------------------------------------
# Validacao de blueprint + empty upstream + config errors
# ---------------------------------------------------------------------------

class TestCompositeValidation:
    def test_empty_upstream_returns_skipped(
        self,
        tmp_path: Path,
        dest_sqlite: str,
        blueprint_nota: dict[str, Any],
        field_mapping_nota: dict[str, str],
    ) -> None:
        # Cria tabela com o schema real mas 0 linhas (simula o que um
        # no upstream real produziria quando nao encontra dados).
        import duckdb as _dd
        db_path = tmp_path / "empty.duckdb"
        _conn = _dd.connect(str(db_path))
        try:
            _conn.execute(
                'CREATE TABLE "src" ('
                '"NUMERO_NOTA" VARCHAR, "CLIENTE_ID" BIGINT, '
                '"PRODUTO" VARCHAR, "QUANTIDADE" BIGINT, "ALIQUOTA" DOUBLE)'
            )
        finally:
            _conn.close()

        processor = CompositeInsertProcessor()
        output = processor.process(
            "comp-empty",
            {
                "connection_string": dest_sqlite,
                "blueprint": blueprint_nota,
                "field_mapping": field_mapping_nota,
            },
            make_context(db_path, "src"),
        )

        assert output["status"] == "skipped"
        assert output["rows_written"] == 0

    def test_missing_connection_string_raises(self) -> None:
        processor = CompositeInsertProcessor()
        with pytest.raises(NodeProcessingError, match="connection_string"):
            processor.process(
                "c",
                {"blueprint": {"tables": [{"alias": "a", "table": "t", "columns": ["x"]}]}},
                {"upstream_results": {}},
            )

    def test_firebird_not_supported(self) -> None:
        processor = CompositeInsertProcessor()
        with pytest.raises(NodeProcessingError, match="firebird"):
            processor.process(
                "c",
                {
                    "connection_string": "firebird+fdb://u:p@h/db",
                    "blueprint": {"tables": [{"alias": "a", "table": "t", "columns": ["x"]}]},
                    "field_mapping": {"a.x": "X"},
                },
                {"upstream_results": {}},
            )

    def test_invalid_blueprint_duplicate_alias(
        self, tmp_path: Path, dest_sqlite: str,
    ) -> None:
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", [{"X": 1}])

        bad_blueprint = {
            "tables": [
                {"alias": "a", "table": "NOTA", "columns": ["numero"]},
                {"alias": "a", "table": "NOTAITEM", "columns": ["produto"]},
            ]
        }
        processor = CompositeInsertProcessor()
        with pytest.raises(NodeProcessingError, match="duplicado"):
            processor.process(
                "c",
                {
                    "connection_string": dest_sqlite,
                    "blueprint": bad_blueprint,
                    "field_mapping": {"a.numero": "X"},
                },
                make_context(db_path, "src"),
            )

    def test_invalid_blueprint_child_references_unknown_parent(
        self, tmp_path: Path, dest_sqlite: str,
    ) -> None:
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", [{"X": 1}])

        bad_blueprint = {
            "tables": [
                {"alias": "a", "table": "NOTA", "columns": ["numero"],
                 "returning": ["id"]},
                {"alias": "b", "table": "NOTAITEM", "role": "child",
                 "parent_alias": "ghost",
                 "fk_map": [{"child_column": "nota_id", "parent_returning": "id"}],
                 "columns": ["produto"]},
            ]
        }
        processor = CompositeInsertProcessor()
        with pytest.raises(NodeProcessingError, match="nao foi declarado"):
            processor.process(
                "c",
                {
                    "connection_string": dest_sqlite,
                    "blueprint": bad_blueprint,
                    "field_mapping": {"a.numero": "X"},
                },
                make_context(db_path, "src"),
            )


# ---------------------------------------------------------------------------
# Teste direto do load_service (isola a camada de IO da camada de processor)
# ---------------------------------------------------------------------------

class TestInsertCompositeDirect:
    def test_returning_ids_propagate_to_children(
        self,
        dest_sqlite: str,
        blueprint_nota: dict[str, Any],
    ) -> None:
        rows = [
            {"NUMERO_NOTA": "A", "CLIENTE_ID": 1,
             "PRODUTO": "P1", "QUANTIDADE": 5, "ALIQUOTA": 17.0},
        ]
        result = load_service.insert_composite(
            dest_sqlite,
            "sqlite",
            blueprint_nota,
            {
                "nota.numero": "NUMERO_NOTA",
                "nota.cliente_id": "CLIENTE_ID",
                "item.produto": "PRODUTO",
                "item.quantidade": "QUANTIDADE",
                "icms.aliquota": "ALIQUOTA",
            },
            rows,
        )
        assert result.status == "success"
        assert result.rows_written == 1

        engine = sa.create_engine(dest_sqlite)
        try:
            with engine.connect() as conn:
                rows_item = conn.execute(sa.text(
                    "SELECT nota_id FROM NOTAITEM"
                )).fetchall()
                rows_nota = conn.execute(sa.text(
                    "SELECT id FROM NOTA"
                )).fetchall()
                assert rows_item[0][0] == rows_nota[0][0]
        finally:
            engine.dispose()
