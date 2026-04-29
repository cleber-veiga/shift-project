"""
Testes para SortNodeProcessor.

Cobre:
  - Ordenacao simples ASC e DESC
  - Multiplas colunas de ordenacao
  - Posicao de nulos (NULLS FIRST / NULLS LAST)
  - Limite de registros
  - Erros de validacao (sem colunas, coluna sem nome)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow.nodes.sort_node import SortNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


class TestSortNodeBasic:

    def test_ordena_asc(self, tmp_path: Path) -> None:
        """Deve retornar linhas ordenadas por VALOR ASC."""
        rows = [
            {"ID": 1, "VALOR": 30},
            {"ID": 2, "VALOR": 10},
            {"ID": 3, "VALOR": 20},
        ]
        db_path = tmp_path / "sort_asc.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {"sort_columns": [{"column": "VALOR", "direction": "asc"}]},
            context,
        )

        out_rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        valores = [r["VALOR"] for r in out_rows]
        assert valores == sorted(valores)

    def test_ordena_desc(self, tmp_path: Path) -> None:
        """Deve retornar linhas ordenadas por VALOR DESC."""
        rows = [
            {"ID": 1, "VALOR": 30},
            {"ID": 2, "VALOR": 10},
            {"ID": 3, "VALOR": 20},
        ]
        db_path = tmp_path / "sort_desc.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {"sort_columns": [{"column": "VALOR", "direction": "desc"}]},
            context,
        )

        out_rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        valores = [r["VALOR"] for r in out_rows]
        assert valores == sorted(valores, reverse=True)

    def test_multiplas_colunas(self, tmp_path: Path) -> None:
        """Deve ordenar por GRUPO ASC e depois VALOR DESC."""
        rows = [
            {"GRUPO": "B", "VALOR": 1},
            {"GRUPO": "A", "VALOR": 5},
            {"GRUPO": "A", "VALOR": 3},
            {"GRUPO": "B", "VALOR": 2},
        ]
        db_path = tmp_path / "sort_multi.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {
                "sort_columns": [
                    {"column": "GRUPO", "direction": "asc"},
                    {"column": "VALOR", "direction": "desc"},
                ]
            },
            context,
        )

        out_rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert out_rows[0]["GRUPO"] == "A"
        assert out_rows[0]["VALOR"] == 5
        assert out_rows[1]["VALOR"] == 3
        assert out_rows[2]["GRUPO"] == "B"
        assert out_rows[2]["VALOR"] == 2

    def test_limit_restringe_saida(self, tmp_path: Path) -> None:
        """Deve retornar apenas N linhas apos a ordenacao."""
        rows = [{"VALOR": i} for i in range(10)]
        db_path = tmp_path / "sort_limit.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {
                "sort_columns": [{"column": "VALOR", "direction": "asc"}],
                "limit": 3,
            },
            context,
        )

        out_rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out_rows) == 3
        assert out_rows[0]["VALOR"] == 0

    def test_nulls_first_desc(self, tmp_path: Path) -> None:
        """Com DESC, nulos devem aparecer primeiro por padrao."""
        rows = [
            {"VALOR": None},
            {"VALOR": 10},
            {"VALOR": 5},
        ]
        db_path = tmp_path / "sort_nulls.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {"sort_columns": [{"column": "VALOR", "direction": "desc"}]},
            context,
        )

        out_rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert out_rows[0]["VALOR"] is None

    def test_nulls_position_override(self, tmp_path: Path) -> None:
        """nulls_position='last' deve colocar nulos no fim mesmo com DESC."""
        rows = [
            {"VALOR": None},
            {"VALOR": 10},
            {"VALOR": 5},
        ]
        db_path = tmp_path / "sort_nulls2.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {
                "sort_columns": [
                    {"column": "VALOR", "direction": "desc", "nulls_position": "last"}
                ]
            },
            context,
        )

        out_rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert out_rows[-1]["VALOR"] is None


class TestSortNodeValidation:

    def test_erro_sem_colunas(self, tmp_path: Path) -> None:
        """Deve lancar NodeProcessingError quando sort_columns esta vazio."""
        rows = [{"ID": 1}]
        db_path = tmp_path / "v.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="ao menos uma coluna"):
            SortNodeProcessor().process("sort-1", {"sort_columns": []}, context)

    def test_erro_coluna_sem_nome(self, tmp_path: Path) -> None:
        """Deve lancar NodeProcessingError quando 'column' esta ausente."""
        rows = [{"ID": 1}]
        db_path = tmp_path / "v2.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="column"):
            SortNodeProcessor().process(
                "sort-1",
                {"sort_columns": [{"column": "", "direction": "asc"}]},
                context,
            )


class TestSortOutputSummary:

    def test_output_summary_tem_row_counts_e_warnings(self, tmp_path: Path) -> None:
        rows = [{"ID": i, "VALOR": 100 - i} for i in range(5)]
        db_path = tmp_path / "sort_summary.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {"sort_columns": [{"column": "VALOR"}]},
            context,
        )

        assert "output_summary" in result
        summary = result["output_summary"]
        assert summary["row_count_in"] == 5
        assert summary["row_count_out"] == 5
        assert summary["warnings"] == []

    def test_limit_diminui_row_count_out(self, tmp_path: Path) -> None:
        rows = [{"ID": i} for i in range(10)]
        db_path = tmp_path / "sort_summary_limit.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SortNodeProcessor().process(
            "sort-1",
            {"sort_columns": [{"column": "ID"}], "limit": 3},
            context,
        )

        summary = result["output_summary"]
        assert summary["row_count_in"] == 10
        assert summary["row_count_out"] == 3
