"""
Testes para RecordIdNodeProcessor.

Cobre:
  - ID sequencial simples (sem particao e sem ordenacao)
  - start_at customizado
  - PARTITION BY (IDs recomeçam por grupo)
  - ORDER BY dentro da janela
  - Erros de validacao (start_at invalido, coluna vazia)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow.nodes.record_id_node import RecordIdNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


class TestRecordIdNodeBasic:

    def test_id_sequencial_simples(self, tmp_path: Path) -> None:
        """Deve adicionar coluna 'id' com valores 1..N."""
        rows = [{"NOME": "A"}, {"NOME": "B"}, {"NOME": "C"}]
        db_path = tmp_path / "rid.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {"id_column": "id"},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        ids = sorted(r["id"] for r in out)
        assert ids == [1, 2, 3]

    def test_start_at_customizado(self, tmp_path: Path) -> None:
        """IDs devem comecar em start_at."""
        rows = [{"NOME": "A"}, {"NOME": "B"}]
        db_path = tmp_path / "rid2.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {"id_column": "seq", "start_at": 100},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        ids = sorted(r["seq"] for r in out)
        assert ids == [100, 101]

    def test_nome_coluna_customizado(self, tmp_path: Path) -> None:
        """Deve usar o nome de coluna informado em id_column."""
        rows = [{"X": 1}, {"X": 2}]
        db_path = tmp_path / "rid3.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {"id_column": "row_num"},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert all("row_num" in r for r in out)
        assert "id" not in out[0]

    def test_preserva_colunas_originais(self, tmp_path: Path) -> None:
        """A coluna de ID deve ser prefixada, as colunas originais preservadas."""
        rows = [{"NOME": "A", "VALOR": 10}]
        db_path = tmp_path / "rid4.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {"id_column": "id"},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert out[0]["NOME"] == "A"
        assert out[0]["VALOR"] == 10
        assert "id" in out[0]


class TestRecordIdNodePartition:

    def test_partition_by_reinicia_contagem(self, tmp_path: Path) -> None:
        """PARTITION BY deve reiniciar a numeracao dentro de cada grupo."""
        rows = [
            {"GRUPO": "A", "ORDEM": 2},
            {"GRUPO": "A", "ORDEM": 1},
            {"GRUPO": "B", "ORDEM": 1},
            {"GRUPO": "B", "ORDEM": 2},
        ]
        db_path = tmp_path / "rid_part.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {
                "id_column": "id",
                "partition_by": ["GRUPO"],
                "order_by": [{"column": "ORDEM", "direction": "asc"}],
            },
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        # Cada grupo deve ter IDs 1 e 2
        a_rows = [r for r in out if r["GRUPO"] == "A"]
        b_rows = [r for r in out if r["GRUPO"] == "B"]
        assert sorted(r["id"] for r in a_rows) == [1, 2]
        assert sorted(r["id"] for r in b_rows) == [1, 2]

    def test_order_by_controla_sequencia(self, tmp_path: Path) -> None:
        """ORDER BY deve controlar qual linha recebe qual ID."""
        rows = [
            {"NOME": "C", "ORDEM": 3},
            {"NOME": "A", "ORDEM": 1},
            {"NOME": "B", "ORDEM": 2},
        ]
        db_path = tmp_path / "rid_order.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {
                "id_column": "id",
                "order_by": [{"column": "ORDEM", "direction": "asc"}],
            },
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        # Ordena resultado pelo campo ORDEM para verificar ID atribuído
        out_sorted = sorted(out, key=lambda r: r["ORDEM"])
        assert out_sorted[0]["id"] == 1
        assert out_sorted[1]["id"] == 2
        assert out_sorted[2]["id"] == 3


class TestRecordIdNodeValidation:

    def test_erro_start_at_invalido(self, tmp_path: Path) -> None:
        rows = [{"X": 1}]
        db_path = tmp_path / "v.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="start_at"):
            RecordIdNodeProcessor().process(
                "rid-1",
                {"id_column": "id", "start_at": "nao_e_numero"},
                context,
            )


class TestRecordIdOutputSummary:

    def test_sem_order_by_emite_warning(self, tmp_path: Path) -> None:
        rows = [{"NOME": "a"}, {"NOME": "b"}, {"NOME": "c"}]
        db_path = tmp_path / "rec_summary_no_order.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {"id_column": "ID"},
            context,
        )

        summary = result["output_summary"]
        assert summary["row_count_in"] == 3
        assert summary["row_count_out"] == 3
        assert "non_deterministic_without_order_by" in summary["warnings"]

    def test_com_order_by_sem_warning(self, tmp_path: Path) -> None:
        rows = [{"NOME": "a"}, {"NOME": "b"}]
        db_path = tmp_path / "rec_summary_with_order.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = RecordIdNodeProcessor().process(
            "rid-1",
            {"id_column": "ID", "order_by": [{"column": "NOME"}]},
            context,
        )

        assert result["output_summary"]["warnings"] == []
