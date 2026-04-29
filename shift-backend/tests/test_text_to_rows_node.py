"""
Testes para TextToRowsNodeProcessor.

Cobre:
  - Explosao basica por delimitador
  - trim_values (espacos removidos por padrao)
  - keep_empty=False (partes vazias filtradas por padrao)
  - output_column diferente de column_to_split
  - max_output_rows limita o resultado
  - row_count_in e row_count_out no summary
  - Fanout 5x: 1k linhas com media de 5 partes = 5k linhas
  - Erros de validacao (coluna ausente, delimitador vazio)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow.nodes.text_to_rows_node import TextToRowsNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


class TestTextToRowsBasic:

    def test_explosao_basica(self, tmp_path: Path) -> None:
        """'a,b,c' → 3 linhas; 2 linhas de entrada = 6 linhas de saida."""
        rows = [
            {"ID": 1, "TAGS": "a,b,c"},
            {"ID": 2, "TAGS": "x,y"},
        ]
        db_path = tmp_path / "tags.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ","},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 5  # 3 + 2
        tags = sorted(r["TAGS"] for r in out)
        assert tags == ["a", "b", "c", "x", "y"]

    def test_trim_values_por_padrao(self, tmp_path: Path) -> None:
        """Espacos ao redor dos valores devem ser removidos."""
        rows = [{"ID": 1, "TAGS": " a , b , c "}]
        db_path = tmp_path / "trim.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ",", "trim_values": True},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        tags = sorted(r["TAGS"] for r in out)
        assert tags == ["a", "b", "c"]

    def test_sem_trim(self, tmp_path: Path) -> None:
        """trim_values=False preserva espacos."""
        rows = [{"ID": 1, "TAGS": " a , b "}]
        db_path = tmp_path / "no_trim.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ",", "trim_values": False},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        tags = [r["TAGS"] for r in out]
        assert " a " in tags

    def test_keep_empty_false_por_padrao(self, tmp_path: Path) -> None:
        """Partes vazias sao filtradas por padrao."""
        rows = [{"ID": 1, "TAGS": "a,,b"}]
        db_path = tmp_path / "empty.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ",", "keep_empty": False},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 2
        assert all(r["TAGS"] for r in out)  # nenhuma string vazia

    def test_keep_empty_true(self, tmp_path: Path) -> None:
        """keep_empty=True preserva partes vazias."""
        rows = [{"ID": 1, "TAGS": "a,,b"}]
        db_path = tmp_path / "empty2.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ",", "keep_empty": True},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 3

    def test_output_column_diferente(self, tmp_path: Path) -> None:
        """output_column diferente renomeia a coluna de saida."""
        rows = [{"ID": 1, "TAGS": "a,b"}]
        db_path = tmp_path / "rename.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {
                "column_to_split": "TAGS",
                "delimiter": ",",
                "output_column": "TAG_ITEM",
            },
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert "TAG_ITEM" in out[0]
        assert "TAGS" not in out[0]
        assert all("ID" in r for r in out)

    def test_max_output_rows_limita(self, tmp_path: Path) -> None:
        """max_output_rows deve limitar o numero de linhas no resultado."""
        rows = [{"ID": i, "TAGS": "a,b,c,d,e"} for i in range(100)]
        db_path = tmp_path / "limit.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {
                "column_to_split": "TAGS",
                "delimiter": ",",
                "max_output_rows": 50,
            },
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 50


class TestTextToRowsSummary:

    def test_row_count_in_out_no_summary(self, tmp_path: Path) -> None:
        """row_count_in e row_count_out devem estar no resultado."""
        rows = [{"ID": i, "TAGS": "a,b"} for i in range(10)]
        db_path = tmp_path / "summary.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ","},
            context,
        )

        assert result["row_count_in"] == 10
        assert result["row_count_out"] == 20
        assert result["avg_fanout"] == 2.0

    def test_fanout_5x_1k_linhas(self, tmp_path: Path) -> None:
        """1000 linhas com 5 partes cada deve produzir 5000 linhas."""
        rows = [{"ID": i, "TAGS": "a,b,c,d,e"} for i in range(1000)]
        db_path = tmp_path / "fanout.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": ","},
            context,
        )

        assert result["row_count_in"] == 1000
        assert result["row_count_out"] == 5000
        assert result["avg_fanout"] == 5.0

    def test_delimitador_multiplo_chars(self, tmp_path: Path) -> None:
        """Delimitador de multiplos caracteres deve funcionar."""
        rows = [{"ID": 1, "TAGS": "a||b||c"}]
        db_path = tmp_path / "multi.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "t2r-1",
            {"column_to_split": "TAGS", "delimiter": "||"},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 3


class TestTextToRowsValidation:

    def test_erro_coluna_ausente(self, tmp_path: Path) -> None:
        """column_to_split vazio deve falhar com erro claro."""
        rows = [{"ID": 1, "TAGS": "a,b"}]
        db_path = tmp_path / "v.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="column_to_split"):
            TextToRowsNodeProcessor().process(
                "t2r-1",
                {"column_to_split": "", "delimiter": ","},
                context,
            )

    def test_erro_delimitador_vazio(self, tmp_path: Path) -> None:
        """delimiter vazio deve falhar com erro claro."""
        rows = [{"ID": 1, "TAGS": "a,b"}]
        db_path = tmp_path / "v2.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="delimiter"):
            TextToRowsNodeProcessor().process(
                "t2r-1",
                {"column_to_split": "TAGS", "delimiter": ""},
                context,
            )


class TestTextToRowsOutputSummary:

    def test_summary_inclui_row_counts(self, tmp_path: Path) -> None:
        rows = [{"ID": 1, "TAGS": "a,b,c"}, {"ID": 2, "TAGS": "x,y"}]
        db_path = tmp_path / "ttr_summary.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "ttr-1",
            {"column_to_split": "TAGS", "delimiter": ","},
            context,
        )

        summary = result["output_summary"]
        assert summary["row_count_in"] == 2
        assert summary["row_count_out"] == 5
        assert summary["warnings"] == []

    def test_high_fanout_emite_warning(self, tmp_path: Path) -> None:
        # 1 linha → 12 partes = fanout 12 > 10 → warning.
        rows = [{"ID": 1, "TAGS": ",".join(f"t{i}" for i in range(12))}]
        db_path = tmp_path / "ttr_fanout.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = TextToRowsNodeProcessor().process(
            "ttr-1",
            {"column_to_split": "TAGS", "delimiter": ","},
            context,
        )

        assert "high_fanout" in result["output_summary"]["warnings"]
