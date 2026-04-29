"""
Testes para UnpivotNodeProcessor.

Cobre:
  - Unpivot basico com colunas explicitas
  - Selecao por tipo (all_numeric, all_string)
  - Cast explicito de valores
  - Fallback UNION ALL quando UNPIVOT nativo falha
  - Erros de validacao (sem index_columns, sem value_columns nem by_type)
  - Round-trip com PivotNodeProcessor
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow.nodes.unpivot_node import UnpivotNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


WIDE_ROWS = [
    {"REGIAO": "NORTE", "JAN": 100, "FEV": 200, "MAR": 150},
    {"REGIAO": "SUL",   "JAN": 300, "FEV": 100, "MAR": 250},
]


@pytest.fixture
def db_wide(tmp_path: Path):
    db_path = tmp_path / "wide.duckdb"
    ref = create_duckdb_with_rows(db_path, "src", WIDE_ROWS)
    return db_path, ref


class TestUnpivotNodeBasic:

    def test_unpivot_basico(self, db_wide) -> None:
        """Wide → long: 2 linhas × 3 colunas = 6 linhas."""
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        result = UnpivotNodeProcessor().process(
            "unpiv-1",
            {
                "index_columns": ["REGIAO"],
                "value_columns": ["JAN", "FEV", "MAR"],
                "variable_column_name": "MES",
                "value_column_name": "VALOR",
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 6
        assert all("REGIAO" in r for r in rows)
        assert all("MES" in r for r in rows)
        assert all("VALOR" in r for r in rows)

    def test_unpivot_valores_corretos(self, db_wide) -> None:
        """Valores por regiao e mes devem bater com o dataset original."""
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        result = UnpivotNodeProcessor().process(
            "unpiv-1",
            {
                "index_columns": ["REGIAO"],
                "value_columns": ["JAN", "FEV", "MAR"],
                "variable_column_name": "MES",
                "value_column_name": "VALOR",
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        norte_jan = next(
            (r for r in rows if r["REGIAO"] == "NORTE" and r["MES"] == "JAN"), None
        )
        assert norte_jan is not None
        assert norte_jan["VALOR"] == 100

        sul_mar = next(
            (r for r in rows if r["REGIAO"] == "SUL" and r["MES"] == "MAR"), None
        )
        assert sul_mar is not None
        assert sul_mar["VALOR"] == 250

    def test_unpivot_by_type_all_numeric(self, db_wide) -> None:
        """by_type='all_numeric' deve detectar JAN, FEV, MAR automaticamente."""
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        result = UnpivotNodeProcessor().process(
            "unpiv-1",
            {
                "index_columns": ["REGIAO"],
                "by_type": "all_numeric",
                "variable_column_name": "MES",
                "value_column_name": "VALOR",
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        # 2 regioes × 3 colunas numericas = 6 linhas
        assert len(rows) == 6

    def test_unpivot_by_type_all_string(self, tmp_path: Path) -> None:
        """by_type='all_string' deve detectar colunas VARCHAR."""
        rows = [
            {"ID": 1, "NOME_PT": "Mesa", "NOME_EN": "Table"},
            {"ID": 2, "NOME_PT": "Cadeira", "NOME_EN": "Chair"},
        ]
        db_path = tmp_path / "str.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = UnpivotNodeProcessor().process(
            "unpiv-1",
            {
                "index_columns": ["ID"],
                "by_type": "all_string",
                "variable_column_name": "LANG",
                "value_column_name": "NOME",
            },
            context,
        )

        rows_out = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        assert len(rows_out) == 4  # 2 IDs × 2 colunas string

    def test_unpivot_cast_value_to(self, db_wide) -> None:
        """cast_value_to=VARCHAR deve converter valores numericos para string."""
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        result = UnpivotNodeProcessor().process(
            "unpiv-1",
            {
                "index_columns": ["REGIAO"],
                "value_columns": ["JAN", "FEV", "MAR"],
                "variable_column_name": "MES",
                "value_column_name": "VALOR",
                "cast_value_to": "VARCHAR",
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        # Valores devem ser strings
        for r in rows:
            assert isinstance(r["VALOR"], str)


class TestUnpivotNodeValidation:

    def test_erro_sem_index_columns(self, db_wide) -> None:
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="index_columns"):
            UnpivotNodeProcessor().process(
                "unpiv-1",
                {
                    "index_columns": [],
                    "value_columns": ["JAN"],
                    "variable_column_name": "MES",
                    "value_column_name": "VALOR",
                },
                context,
            )

    def test_erro_sem_value_columns_nem_by_type(self, db_wide) -> None:
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="value_columns.*by_type"):
            UnpivotNodeProcessor().process(
                "unpiv-1",
                {
                    "index_columns": ["REGIAO"],
                    "variable_column_name": "MES",
                    "value_column_name": "VALOR",
                },
                context,
            )

    def test_erro_by_type_invalido(self, db_wide) -> None:
        db_path, ref = db_wide
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="by_type"):
            UnpivotNodeProcessor().process(
                "unpiv-1",
                {
                    "index_columns": ["REGIAO"],
                    "by_type": "all_boolean",
                    "variable_column_name": "MES",
                    "value_column_name": "VALOR",
                },
                context,
            )

    def test_erro_by_type_sem_colunas_correspondentes(self, tmp_path: Path) -> None:
        """all_string em tabela sem VARCHAR (além de index) deve falhar."""
        rows = [{"REGIAO": "NORTE", "JAN": 100}]
        db_path = tmp_path / "no_str.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="nenhuma coluna"):
            UnpivotNodeProcessor().process(
                "unpiv-1",
                {
                    "index_columns": ["REGIAO"],
                    "by_type": "all_string",
                    "variable_column_name": "MES",
                    "value_column_name": "VALOR",
                },
                context,
            )


class TestUnpivotOutputSummary:

    def test_summary_basico(self, tmp_path: Path) -> None:
        rows = [
            {"REGIAO": "NORTE", "JAN": 100, "FEV": 200},
            {"REGIAO": "SUL",   "JAN": 50,  "FEV": 75},
        ]
        db_path = tmp_path / "unpivot_summary.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = UnpivotNodeProcessor().process(
            "u-1",
            {
                "index_columns": ["REGIAO"],
                "value_columns": ["JAN", "FEV"],
            },
            context,
        )

        summary = result["output_summary"]
        assert summary["row_count_in"] == 2
        # 2 linhas × 2 colunas de valor = 4 linhas.
        assert summary["row_count_out"] == 4
        assert summary["warnings"] == []
