"""
Testes de integracao para o loader SQLAlchemy do migrator.

Usa SQLite como banco de destino (disponivel sem dependencias extras).
Para forcar o uso do loader SQLAlchemy direto (que e o caminho Oracle/Firebird),
chamamos _load_via_sqlalchemy diretamente — o run_migration_pipeline roteia
SQLite para o dlt, que tem limitacoes de merge nao relevantes para o Oracle.

Cobre:
  - append: insere linhas sem verificar duplicatas
  - replace: trunca e reinsere
  - merge: UPSERT — insere quando a chave nao existe, atualiza quando existe
  - Criacao automatica da tabela de destino quando nao existe
  - merge_key obrigatorio quando write_disposition='merge'
  - Chave composta (dois campos)
  - Leitura de fonte DuckDB (staging)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.data_pipelines.migrator import _load_via_sqlalchemy
from tests.conftest import create_duckdb_with_rows


# ---------------------------------------------------------------------------
# Fixtures especificas do migrator
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(tmp_path: Path) -> str:
    """Retorna a connection string de um banco SQLite temporario."""
    db_file = tmp_path / "dest.db"
    return f"sqlite:///{db_file}"


@pytest.fixture
def source_duckdb(tmp_path: Path) -> tuple[str, str]:
    """Cria um banco DuckDB de staging com dados de exemplo e retorna (conn_str, table_name)."""
    rows = [
        {"ID": 1, "NOME": "Alpha", "VALOR": 100.0},
        {"ID": 2, "NOME": "Beta",  "VALOR": 200.0},
        {"ID": 3, "NOME": "Gamma", "VALOR": 300.0},
    ]
    db_path = tmp_path / "source.duckdb"
    create_duckdb_with_rows(db_path, "dados", rows)
    return f"duckdb:///{db_path}", "dados"


def read_sqlite_table(conn_str: str, table_name: str) -> list[dict[str, Any]]:
    """Le todas as linhas de uma tabela SQLite."""
    engine = sa.create_engine(conn_str)
    try:
        with engine.connect() as conn:
            result = conn.execute(sa.text(f'SELECT * FROM "{table_name}"'))
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        engine.dispose()


def load_sqlalchemy(
    source_conn: str,
    dest_conn: str,
    source_table: str,
    target_table: str,
    write_disposition: str = "append",
    merge_key: list[str] | None = None,
) -> dict[str, Any]:
    """Helper que chama _load_via_sqlalchemy diretamente (caminho Oracle/Firebird)."""
    return _load_via_sqlalchemy(
        source_connection=source_conn,
        destination_connection=dest_conn,
        target_table=target_table,
        query=f'SELECT * FROM "{source_table}"',
        chunk_size=1000,
        write_disposition=write_disposition,
        merge_key=merge_key or [],
    )


# ---------------------------------------------------------------------------
# Testes de append
# ---------------------------------------------------------------------------

class TestMigratorAppend:

    def test_append_cria_tabela_e_insere(
        self, source_duckdb: tuple[str, str], sqlite_db: str
    ) -> None:
        """Deve criar a tabela e inserir as linhas quando ela nao existe."""
        source_conn, table_name = source_duckdb

        result = load_sqlalchemy(source_conn, sqlite_db, table_name, "destino")

        assert result["rows_loaded"] == 3
        rows = read_sqlite_table(sqlite_db, "destino")
        assert len(rows) == 3
        assert {r["NOME"] for r in rows} == {"Alpha", "Beta", "Gamma"}

    def test_append_nao_remove_dados_existentes(
        self, source_duckdb: tuple[str, str], sqlite_db: str
    ) -> None:
        """Append executado duas vezes deve duplicar as linhas."""
        source_conn, table_name = source_duckdb

        load_sqlalchemy(source_conn, sqlite_db, table_name, "destino")
        load_sqlalchemy(source_conn, sqlite_db, table_name, "destino")

        rows = read_sqlite_table(sqlite_db, "destino")
        assert len(rows) == 6  # 3 + 3

    def test_append_retorna_zero_quando_fonte_vazia(
        self, tmp_path: Path, sqlite_db: str
    ) -> None:
        """Deve retornar rows_loaded=0 quando a fonte nao tem dados."""
        db_path = tmp_path / "empty.duckdb"
        create_duckdb_with_rows(db_path, "vazio", [])

        result = load_sqlalchemy(
            f"duckdb:///{db_path}", sqlite_db, "vazio", "destino"
        )
        assert result["rows_loaded"] == 0


# ---------------------------------------------------------------------------
# Testes de replace
# ---------------------------------------------------------------------------

class TestMigratorReplace:

    def test_replace_substitui_dados_existentes(
        self, source_duckdb: tuple[str, str], sqlite_db: str, tmp_path: Path
    ) -> None:
        """Replace deve truncar a tabela e reinserir os novos dados."""
        source_conn, table_name = source_duckdb

        # Primeira carga
        load_sqlalchemy(source_conn, sqlite_db, table_name, "destino")

        # Segunda carga com dados diferentes via replace
        new_rows = [{"ID": 10, "NOME": "Delta", "VALOR": 999.0}]
        new_db = tmp_path / "new_source.duckdb"
        create_duckdb_with_rows(new_db, "novos", new_rows)

        load_sqlalchemy(
            f"duckdb:///{new_db}", sqlite_db, "novos", "destino",
            write_disposition="replace",
        )

        rows = read_sqlite_table(sqlite_db, "destino")
        assert len(rows) == 1
        assert rows[0]["NOME"] == "Delta"


# ---------------------------------------------------------------------------
# Testes de merge (UPSERT)
# ---------------------------------------------------------------------------

class TestMigratorMerge:

    def test_merge_insere_quando_chave_nao_existe(
        self, source_duckdb: tuple[str, str], sqlite_db: str
    ) -> None:
        """Merge deve inserir linhas quando a chave ainda nao existe no destino."""
        source_conn, table_name = source_duckdb

        result = load_sqlalchemy(
            source_conn, sqlite_db, table_name, "destino",
            write_disposition="merge",
            merge_key=["ID"],
        )

        assert result["rows_loaded"] == 3
        rows = read_sqlite_table(sqlite_db, "destino")
        assert len(rows) == 3

    def test_merge_atualiza_quando_chave_existe(
        self, source_duckdb: tuple[str, str], sqlite_db: str, tmp_path: Path
    ) -> None:
        """Merge deve atualizar NOME e VALOR quando ID ja existe no destino."""
        source_conn, table_name = source_duckdb

        # Primeira carga: insere IDs 1, 2, 3
        load_sqlalchemy(
            source_conn, sqlite_db, table_name, "destino",
            write_disposition="merge",
            merge_key=["ID"],
        )

        # Segunda carga: ID 1 com novo NOME, ID 4 novo
        update_rows = [
            {"ID": 1, "NOME": "Alpha ATUALIZADO", "VALOR": 999.0},
            {"ID": 4, "NOME": "Delta", "VALOR": 400.0},
        ]
        update_db = tmp_path / "update.duckdb"
        create_duckdb_with_rows(update_db, "atualizacoes", update_rows)

        load_sqlalchemy(
            f"duckdb:///{update_db}", sqlite_db, "atualizacoes", "destino",
            write_disposition="merge",
            merge_key=["ID"],
        )

        rows = read_sqlite_table(sqlite_db, "destino")
        rows_by_id = {r["ID"]: r for r in rows}

        # Deve ter 4 registros: 1 (atualizado), 2, 3, 4 (novo)
        assert len(rows) == 4
        assert rows_by_id[1]["NOME"] == "Alpha ATUALIZADO"
        assert rows_by_id[1]["VALOR"] == pytest.approx(999.0)
        assert rows_by_id[2]["NOME"] == "Beta"  # nao alterado
        assert rows_by_id[4]["NOME"] == "Delta"  # inserido

    def test_merge_sem_merge_key_levanta_erro(
        self, source_duckdb: tuple[str, str], sqlite_db: str
    ) -> None:
        """Deve lancar ValueError quando merge_key nao e informado."""
        source_conn, table_name = source_duckdb

        with pytest.raises(ValueError, match="merge_key"):
            load_sqlalchemy(
                source_conn, sqlite_db, table_name, "destino",
                write_disposition="merge",
                merge_key=[],
            )

    def test_merge_com_chave_composta(
        self, sqlite_db: str, tmp_path: Path
    ) -> None:
        """Merge deve funcionar com chave composta (dois campos)."""
        rows = [
            {"ANO": 2024, "MES": 1, "VALOR": 100.0},
            {"ANO": 2024, "MES": 2, "VALOR": 200.0},
            {"ANO": 2025, "MES": 1, "VALOR": 300.0},
        ]
        db_path = tmp_path / "composta.duckdb"
        create_duckdb_with_rows(db_path, "dados", rows)

        load_sqlalchemy(
            f"duckdb:///{db_path}", sqlite_db, "dados", "destino",
            write_disposition="merge",
            merge_key=["ANO", "MES"],
        )

        # Atualiza ANO=2024, MES=1
        update_rows = [{"ANO": 2024, "MES": 1, "VALOR": 999.0}]
        update_db = tmp_path / "update_composta.duckdb"
        create_duckdb_with_rows(update_db, "atualizacoes", update_rows)

        load_sqlalchemy(
            f"duckdb:///{update_db}", sqlite_db, "atualizacoes", "destino",
            write_disposition="merge",
            merge_key=["ANO", "MES"],
        )

        rows_dest = read_sqlite_table(sqlite_db, "destino")
        assert len(rows_dest) == 3

        row_jan_24 = next(
            r for r in rows_dest if r["ANO"] == 2024 and r["MES"] == 1
        )
        assert row_jan_24["VALOR"] == pytest.approx(999.0)

        row_fev_24 = next(
            r for r in rows_dest if r["ANO"] == 2024 and r["MES"] == 2
        )
        assert row_fev_24["VALOR"] == pytest.approx(200.0)  # nao alterado
