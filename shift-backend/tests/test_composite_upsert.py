"""
Testes do modo upsert / insert_or_ignore no no ``composite_insert``.

Cobertura:
  - Geracao de SQL por dialeto (postgres, sqlite, oracle) via
    ``_build_upsert_sql`` — testes unitarios de string SQL.
  - Comportamento end-to-end contra SQLite real (suporta RETURNING +
    ON CONFLICT desde 3.35).
  - Validacao: conflict_keys vazio, dialeto nao suportado, rollback
    em cascata quando filho falha apos parent ser atualizado via UPSERT.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.services.load_service import (
    _build_upsert_sql,
    load_service,
)
from app.services.workflow.nodes.composite_insert import CompositeInsertProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import create_duckdb_with_rows, make_context


# ---------------------------------------------------------------------------
# Fixture: SQLite com UNIQUE constraint para habilitar ON CONFLICT
# ---------------------------------------------------------------------------

@pytest.fixture
def dest_sqlite_upsert(tmp_path: Path) -> str:
    """SQLite com NOTA.numero UNIQUE + NOTAITEM (numero, produto) UNIQUE."""
    db_file = tmp_path / "upsert.sqlite"
    cs = f"sqlite:///{db_file}"
    engine = sa.create_engine(cs)
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE NOTA (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero VARCHAR(50) NOT NULL UNIQUE,
                cliente_id INTEGER NOT NULL,
                valor DOUBLE
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE NOTAITEM (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nota_id INTEGER NOT NULL,
                produto VARCHAR(100) NOT NULL,
                quantidade INTEGER NOT NULL,
                UNIQUE (nota_id, produto)
            )
        """))
    engine.dispose()
    return cs


def _count(cs: str, table: str) -> int:
    engine = sa.create_engine(cs)
    try:
        with engine.connect() as conn:
            return (
                conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()
                or 0
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Testes unitarios de geracao de SQL por dialeto
# ---------------------------------------------------------------------------


class TestBuildUpsertSql:
    def test_upsert_postgres_on_conflict(self) -> None:
        stmts = _build_upsert_sql(
            conn_type="postgres",
            table="NOTA",
            columns=["numero", "cliente_id", "valor"],
            conflict_mode="upsert",
            conflict_keys=["numero"],
            update_columns=None,
            returning=["id"],
        )
        sql = stmts.primary
        assert 'INSERT INTO "NOTA"' in sql
        assert "ON CONFLICT" in sql and '"numero"' in sql
        assert "DO UPDATE SET" in sql
        assert '"cliente_id" = EXCLUDED."cliente_id"' in sql
        assert '"valor" = EXCLUDED."valor"' in sql
        # conflict_key NAO deve aparecer no SET (nao se atualiza a propria key).
        assert '"numero" = EXCLUDED."numero"' not in sql
        assert "RETURNING" in sql and '"id"' in sql
        assert stmts.fetch_existing is not None
        assert stmts.always_fetch is False

    def test_upsert_sqlite_on_conflict(self) -> None:
        stmts = _build_upsert_sql(
            conn_type="sqlite",
            table="NOTA",
            columns=["numero", "valor"],
            conflict_mode="upsert",
            conflict_keys=["numero"],
            update_columns=["valor"],
            returning=["id"],
        )
        sql = stmts.primary
        assert "ON CONFLICT" in sql
        assert '"valor" = EXCLUDED."valor"' in sql
        assert "RETURNING" in sql
        assert stmts.always_fetch is False

    def test_upsert_oracle_merge(self) -> None:
        stmts = _build_upsert_sql(
            conn_type="oracle",
            table="NOTA",
            columns=["numero", "cliente_id", "valor"],
            conflict_mode="upsert",
            conflict_keys=["numero"],
            update_columns=None,
            returning=["id"],
        )
        sql = stmts.primary
        assert sql.startswith('MERGE INTO "NOTA" t')
        assert "FROM dual" in sql
        assert 't."numero" = s."numero"' in sql
        assert "WHEN MATCHED THEN UPDATE SET" in sql
        assert 't."cliente_id" = s."cliente_id"' in sql
        assert "WHEN NOT MATCHED THEN INSERT" in sql
        # Oracle MERGE nao retorna — sempre precisa fetch.
        assert stmts.always_fetch is True
        assert stmts.fetch_existing is not None

    def test_upsert_mysql_blocked(self) -> None:
        with pytest.raises(ValueError, match="nao suportado"):
            _build_upsert_sql(
                conn_type="mysql",
                table="NOTA",
                columns=["numero"],
                conflict_mode="upsert",
                conflict_keys=["numero"],
                update_columns=None,
                returning=[],
            )

    def test_insert_or_ignore_uses_do_nothing(self) -> None:
        stmts = _build_upsert_sql(
            conn_type="postgres",
            table="NOTA",
            columns=["numero", "valor"],
            conflict_mode="insert_or_ignore",
            conflict_keys=["numero"],
            update_columns=None,
            returning=["id"],
        )
        assert "DO NOTHING" in stmts.primary
        assert "DO UPDATE" not in stmts.primary
        # fetch_existing obrigatorio: DO NOTHING pode nao retornar.
        assert stmts.fetch_existing is not None


# ---------------------------------------------------------------------------
# Testes end-to-end contra SQLite (real I/O)
# ---------------------------------------------------------------------------


def _blueprint_upsert_numero() -> dict[str, Any]:
    return {
        "tables": [
            {
                "alias": "nota",
                "table": "NOTA",
                "role": "header",
                "columns": ["numero", "cliente_id", "valor"],
                "returning": ["id"],
                "conflict_mode": "upsert",
                "conflict_keys": ["numero"],
                "update_columns": None,
            }
        ]
    }


class TestUpsertEndToEnd:
    def test_upsert_returning_id_on_insert_path(
        self, tmp_path: Path, dest_sqlite_upsert: str,
    ) -> None:
        source_rows = [
            {"NUM": "N001", "CLIENTE": 10, "VALOR": 100.0},
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)

        processor = CompositeInsertProcessor()
        output = processor.process(
            "upsert-insert",
            {
                "connection_string": dest_sqlite_upsert,
                "blueprint": _blueprint_upsert_numero(),
                "field_mapping": {
                    "nota.numero": "NUM",
                    "nota.cliente_id": "CLIENTE",
                    "nota.valor": "VALOR",
                },
            },
            make_context(db_path, "src"),
        )

        assert output["status"] == "success"
        assert output["rows_written"] == 1
        assert _count(dest_sqlite_upsert, "NOTA") == 1

    def test_upsert_returning_id_on_update_path(
        self, tmp_path: Path, dest_sqlite_upsert: str,
    ) -> None:
        # Pre-insere N001 e captura o id. Depois roda upsert com o mesmo
        # numero mas valor diferente — deve UPDATE, mantendo o mesmo id.
        engine = sa.create_engine(dest_sqlite_upsert)
        try:
            with engine.begin() as conn:
                res = conn.execute(sa.text(
                    "INSERT INTO NOTA (numero, cliente_id, valor) "
                    "VALUES ('N999', 7, 100.0) RETURNING id"
                ))
                original_id = res.scalar()
        finally:
            engine.dispose()
        assert original_id is not None

        source_rows = [
            {"NUM": "N999", "CLIENTE": 7, "VALOR": 250.0},
        ]
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", source_rows)

        result = load_service.insert_composite(
            dest_sqlite_upsert,
            "sqlite",
            _blueprint_upsert_numero(),
            {
                "nota.numero": "NUM",
                "nota.cliente_id": "CLIENTE",
                "nota.valor": "VALOR",
            },
            [{"NUM": "N999", "CLIENTE": 7, "VALOR": 250.0}],
        )
        assert result.status == "success"
        assert _count(dest_sqlite_upsert, "NOTA") == 1

        engine = sa.create_engine(dest_sqlite_upsert)
        try:
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT id, valor FROM NOTA WHERE numero = 'N999'"
                )).one()
                # Mesmo id, valor atualizado.
                assert row.id == original_id
                assert row.valor == 250.0
        finally:
            engine.dispose()

    def test_insert_or_ignore_skips_existing(
        self, tmp_path: Path, dest_sqlite_upsert: str,
    ) -> None:
        # Pre-insere N001; roda insert_or_ignore com mesmo numero mas
        # VALOR diferente — deve ignorar (valor original preservado).
        engine = sa.create_engine(dest_sqlite_upsert)
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "INSERT INTO NOTA (numero, cliente_id, valor) "
                    "VALUES ('N001', 1, 50.0)"
                ))
        finally:
            engine.dispose()

        blueprint = _blueprint_upsert_numero()
        blueprint["tables"][0]["conflict_mode"] = "insert_or_ignore"
        blueprint["tables"][0]["update_columns"] = None

        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", [{"NUM": "N001"}])

        result = load_service.insert_composite(
            dest_sqlite_upsert,
            "sqlite",
            blueprint,
            {
                "nota.numero": "NUM",
                "nota.cliente_id": "NUM",   # nao usaremos, mas precisa algo
                "nota.valor": "NUM",
            },
            [{"NUM": "N001"}],
        )
        # A linha fonte existe — mas o DB ja tinha N001; nao deve inserir nem atualizar.
        assert result.status == "success"
        assert _count(dest_sqlite_upsert, "NOTA") == 1

        engine = sa.create_engine(dest_sqlite_upsert)
        try:
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT cliente_id, valor FROM NOTA WHERE numero = 'N001'"
                )).one()
                # Valor original intacto (insert_or_ignore nao sobrescreve).
                assert row.cliente_id == 1
                assert row.valor == 50.0
        finally:
            engine.dispose()

    def test_transaction_rolls_back_all_tables_on_upsert_error(
        self, tmp_path: Path, dest_sqlite_upsert: str,
    ) -> None:
        # Cenario: NOTA ja tem 'N500' com valor=100. Upsert tenta atualizar
        # para valor=999 e inserir NOTAITEM com quantidade=NULL (viola NOT NULL).
        # Apos rollback: NOTA.valor deve continuar 100.
        engine = sa.create_engine(dest_sqlite_upsert)
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "INSERT INTO NOTA (numero, cliente_id, valor) "
                    "VALUES ('N500', 5, 100.0)"
                ))
        finally:
            engine.dispose()

        blueprint: dict[str, Any] = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero", "cliente_id", "valor"],
                    "returning": ["id"],
                    "conflict_mode": "upsert",
                    "conflict_keys": ["numero"],
                },
                {
                    "alias": "item",
                    "table": "NOTAITEM",
                    "role": "child",
                    "parent_alias": "nota",
                    "fk_map": [{"child_column": "nota_id", "parent_returning": "id"}],
                    "columns": ["produto", "quantidade"],
                    "returning": [],
                },
            ]
        }
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", [
            {"NUM": "N500", "CLIENTE": 5, "VALOR": 999.0,
             "PROD": "X", "QTD": None},
        ])

        result = load_service.insert_composite(
            dest_sqlite_upsert,
            "sqlite",
            blueprint,
            {
                "nota.numero": "NUM",
                "nota.cliente_id": "CLIENTE",
                "nota.valor": "VALOR",
                "item.produto": "PROD",
                "item.quantidade": "QTD",
            },
            [{"NUM": "N500", "CLIENTE": 5, "VALOR": 999.0,
              "PROD": "X", "QTD": None}],
        )
        assert result.status == "error"
        assert result.failed_at_alias == "item"

        # NOTA.valor deve estar no valor original — rollback reverteu UPDATE.
        engine = sa.create_engine(dest_sqlite_upsert)
        try:
            with engine.connect() as conn:
                valor = conn.execute(sa.text(
                    "SELECT valor FROM NOTA WHERE numero = 'N500'"
                )).scalar()
                assert valor == 100.0
                # NOTAITEM nao recebeu nada.
                assert conn.execute(sa.text(
                    "SELECT COUNT(*) FROM NOTAITEM"
                )).scalar() == 0
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Validacoes de blueprint invalido
# ---------------------------------------------------------------------------


class TestUpsertValidation:
    def test_empty_conflict_keys_raises_validation(
        self, tmp_path: Path, dest_sqlite_upsert: str,
    ) -> None:
        bad_blueprint = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero"],
                    "returning": [],
                    "conflict_mode": "upsert",
                    "conflict_keys": [],  # vazio — proibido
                },
            ]
        }
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", [{"NUM": "X"}])

        processor = CompositeInsertProcessor()
        with pytest.raises(NodeProcessingError, match="conflict_keys"):
            processor.process(
                "c",
                {
                    "connection_string": dest_sqlite_upsert,
                    "blueprint": bad_blueprint,
                    "field_mapping": {"nota.numero": "NUM"},
                },
                make_context(db_path, "src"),
            )

    def test_invalid_update_column_raises(
        self, tmp_path: Path, dest_sqlite_upsert: str,
    ) -> None:
        bad_blueprint = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero", "valor"],
                    "returning": [],
                    "conflict_mode": "upsert",
                    "conflict_keys": ["numero"],
                    "update_columns": ["nao_existe"],  # fora de columns
                },
            ]
        }
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(db_path, "src", [{"NUM": "X", "V": 1}])

        processor = CompositeInsertProcessor()
        with pytest.raises(NodeProcessingError, match="update_columns"):
            processor.process(
                "c",
                {
                    "connection_string": dest_sqlite_upsert,
                    "blueprint": bad_blueprint,
                    "field_mapping": {"nota.numero": "NUM", "nota.valor": "V"},
                },
                make_context(db_path, "src"),
            )
