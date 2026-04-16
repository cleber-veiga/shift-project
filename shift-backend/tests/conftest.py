"""
Fixtures compartilhadas entre todos os testes de nos de transformacao.

Estrategia de teste:
  - Cada no e testado diretamente via seu processador (sem orquestrador).
  - O banco DuckDB e criado em um arquivo temporario por teste (tmp_path do pytest).
  - O contexto simula o que o dynamic_runner passaria para o no.
  - Os dados de saida sao verificados lendo a tabela DuckDB resultante.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Helpers de banco de dados
# ---------------------------------------------------------------------------

def create_duckdb_with_rows(
    db_path: Path,
    table_name: str,
    rows: list[dict[str, Any]],
    schema: str | None = None,
) -> dict[str, Any]:
    """
    Cria um banco DuckDB com uma tabela populada e retorna a DuckDbReference.

    Quando schema e informado, a tabela e criada dentro desse schema
    (simulando o comportamento do dlt com shift_extract).
    """
    conn = duckdb.connect(str(db_path))
    try:
        if schema:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            full_table = f'"{schema}"."{table_name}"'
        else:
            full_table = f'"{table_name}"'

        if not rows:
            conn.execute(f"CREATE OR REPLACE TABLE {full_table} (dummy VARCHAR)")
        else:
            sample = rows[0]
            col_defs = []
            for col, val in sample.items():
                if isinstance(val, bool):
                    col_defs.append(f'"{col}" BOOLEAN')
                elif isinstance(val, int):
                    col_defs.append(f'"{col}" BIGINT')
                elif isinstance(val, float):
                    col_defs.append(f'"{col}" DOUBLE')
                else:
                    col_defs.append(f'"{col}" VARCHAR')
            conn.execute(
                f"CREATE OR REPLACE TABLE {full_table} ({', '.join(col_defs)})"
            )
            for row in rows:
                placeholders = ", ".join(["?" for _ in row])
                conn.execute(
                    f"INSERT INTO {full_table} VALUES ({placeholders})",
                    list(row.values()),
                )
    finally:
        conn.close()

    return {
        "storage_type": "duckdb",
        "database_path": str(db_path),
        "table_name": table_name,
        "dataset_name": schema,
    }


def read_duckdb_table(db_path: str, table_name: str) -> list[dict[str, Any]]:
    """Le todas as linhas de uma tabela DuckDB e retorna como lista de dicts."""
    conn = duckdb.connect(db_path, read_only=True)
    try:
        result = conn.execute(f'SELECT * FROM main."{table_name}"')
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures de contexto
# ---------------------------------------------------------------------------

def make_context(
    db_path: Path,
    table_name: str,
    schema: str | None = None,
    execution_id: str = "test-exec-001",
) -> dict[str, Any]:
    """
    Monta o contexto que o dynamic_runner passaria para um no.

    O contexto contem upstream_results com uma referencia DuckDB apontando
    para a tabela criada pelo no anterior.
    """
    return {
        "execution_id": execution_id,
        "workflow_id": "test-workflow-001",
        "upstream_results": {
            "upstream-node": {
                "node_id": "upstream-node",
                "status": "completed",
                "output_field": "data",
                "data": {
                    "storage_type": "duckdb",
                    "database_path": str(db_path),
                    "table_name": table_name,
                    "dataset_name": schema,
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# Fixtures pytest
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_rows() -> list[dict[str, Any]]:
    """Linhas de exemplo representando itens de nota fiscal."""
    return [
        {"NUMERO_NOTA": 1001, "QUANTIDADE": 2, "VALOR_UNITARIO": 100.0, "DESCONTO": 0.0, "PRODUTO": "CADEIRA"},
        {"NUMERO_NOTA": 1001, "QUANTIDADE": 3, "VALOR_UNITARIO": 50.0,  "DESCONTO": 10.0, "PRODUTO": "MESA"},
        {"NUMERO_NOTA": 1002, "QUANTIDADE": 1, "VALOR_UNITARIO": 200.0, "DESCONTO": 0.0, "PRODUTO": "SOFA"},
        {"NUMERO_NOTA": 1003, "QUANTIDADE": 5, "VALOR_UNITARIO": 20.0,  "DESCONTO": 5.0, "PRODUTO": "LAMPADA"},
    ]


@pytest.fixture
def duckdb_with_sample(tmp_path: Path, sample_rows: list[dict[str, Any]]):
    """
    Retorna (db_path, reference) com a tabela de exemplo criada no schema main.
    """
    db_path = tmp_path / "test.duckdb"
    reference = create_duckdb_with_rows(db_path, "source_data", sample_rows)
    return db_path, reference


@pytest.fixture
def duckdb_with_dlt_schema(tmp_path: Path, sample_rows: list[dict[str, Any]]):
    """
    Retorna (db_path, reference) com a tabela criada no schema shift_extract,
    simulando o comportamento do dlt.
    """
    db_path = tmp_path / "test_dlt.duckdb"
    reference = create_duckdb_with_rows(
        db_path, "source_data", sample_rows, schema="shift_extract"
    )
    return db_path, reference
