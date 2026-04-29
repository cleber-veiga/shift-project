"""
Testes para UnionNodeProcessor.

Cobre:
  - UNION BY NAME (colunas alinhadas pelo nome)
  - UNION BY POSITION (colunas alinhadas pela posicao)
  - Coluna de origem (_source) opcional
  - Bancos DuckDB distintos (ATTACH automatico)
  - Erros de validacao (< 2 entradas, mode invalido)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow.nodes.union_node import UnionNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import read_duckdb_table, create_duckdb_with_rows


def make_union_context(
    refs: list[tuple[str, dict]],
    execution_id: str = "test-exec",
) -> dict:
    """Monta contexto simulando N entradas com handles input_1..input_N."""
    edge_handles = {}
    upstream_results = {}
    for i, (node_id, ref) in enumerate(refs, start=1):
        handle = f"input_{i}"
        edge_handles[node_id] = handle
        upstream_results[node_id] = {
            "node_id": node_id,
            "status": "completed",
            "output_field": "data",
            "data": ref,
        }
    return {
        "execution_id": execution_id,
        "workflow_id": "test-workflow",
        "edge_handles": edge_handles,
        "upstream_results": upstream_results,
    }


class TestUnionNodeByName:

    def test_union_basico_by_name(self, tmp_path: Path) -> None:
        """Deve combinar dois datasets com as mesmas colunas."""
        rows_a = [{"ID": 1, "NOME": "Alice"}]
        rows_b = [{"ID": 2, "NOME": "Bob"}]
        db = tmp_path / "u.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", rows_a)
        ref_b = create_duckdb_with_rows(db, "b", rows_b)
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process("union-1", {"mode": "by_name"}, context)

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 2
        ids = sorted(r["ID"] for r in out)
        assert ids == [1, 2]

    def test_union_by_name_colunas_extras_viram_null(self, tmp_path: Path) -> None:
        """Colunas presentes em apenas um lado ficam NULL no outro."""
        rows_a = [{"ID": 1, "NOME": "Alice"}]
        rows_b = [{"ID": 2, "CODIGO": 99}]
        db = tmp_path / "u2.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", rows_a)
        ref_b = create_duckdb_with_rows(db, "b", rows_b)
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process("union-1", {"mode": "by_name"}, context)

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 2
        # Todas as colunas devem existir
        for row in out:
            assert "ID" in row
            assert "NOME" in row
            assert "CODIGO" in row

    def test_union_tres_entradas(self, tmp_path: Path) -> None:
        """Deve combinar 3 datasets."""
        db = tmp_path / "u3.duckdb"
        refs = []
        for i in range(3):
            ref = create_duckdb_with_rows(db, f"src_{i}", [{"ID": i}])
            refs.append((f"node-{i}", ref))
        context = make_union_context(refs)

        result = UnionNodeProcessor().process("union-1", {"mode": "by_name"}, context)

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 3


class TestUnionNodeByPosition:

    def test_union_by_position(self, tmp_path: Path) -> None:
        """BY POSITION deve empilhar colunas na posicao, ignorando nomes."""
        rows_a = [{"A": 1, "B": 2}]
        rows_b = [{"C": 3, "D": 4}]
        db = tmp_path / "pos.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", rows_a)
        ref_b = create_duckdb_with_rows(db, "b", rows_b)
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process("union-1", {"mode": "by_position"}, context)

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 2


class TestUnionNodeSourceColumn:

    def test_add_source_col(self, tmp_path: Path) -> None:
        """Deve adicionar coluna com o handle de origem quando add_source_col=True."""
        db = tmp_path / "src_col.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", [{"ID": 1}])
        ref_b = create_duckdb_with_rows(db, "b", [{"ID": 2}])
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process(
            "union-1",
            {"mode": "by_name", "add_source_col": True, "source_col_name": "_src"},
            context,
        )

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        sources = {r["_src"] for r in out}
        assert sources == {"input_1", "input_2"}


class TestUnionNodeDistinctDatabases:

    def test_union_bancos_distintos(self, tmp_path: Path) -> None:
        """Deve realizar ATTACH e UNION entre dois bancos DuckDB distintos."""
        db_a = tmp_path / "db_a.duckdb"
        db_b = tmp_path / "db_b.duckdb"
        ref_a = create_duckdb_with_rows(db_a, "a", [{"ID": 10, "NOME": "X"}])
        ref_b = create_duckdb_with_rows(db_b, "b", [{"ID": 20, "NOME": "Y"}])
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process("union-1", {"mode": "by_name"}, context)

        out = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(out) == 2
        ids = sorted(r["ID"] for r in out)
        assert ids == [10, 20]


class TestUnionNodeValidation:

    def test_erro_menos_de_duas_entradas(self, tmp_path: Path) -> None:
        """Deve lancar NodeProcessingError se apenas 1 entrada estiver conectada."""
        db = tmp_path / "v.duckdb"
        ref = create_duckdb_with_rows(db, "src", [{"ID": 1}])
        context = make_union_context([("node-a", ref)])

        with pytest.raises(NodeProcessingError, match="ao menos 2"):
            UnionNodeProcessor().process("union-1", {"mode": "by_name"}, context)

    def test_erro_mode_invalido(self, tmp_path: Path) -> None:
        db = tmp_path / "v2.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", [{"ID": 1}])
        ref_b = create_duckdb_with_rows(db, "b", [{"ID": 2}])
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        with pytest.raises(NodeProcessingError, match="mode"):
            UnionNodeProcessor().process("union-1", {"mode": "intersect"}, context)


class TestUnionOutputSummary:

    def test_summary_dict_por_handle(self, tmp_path: Path) -> None:
        rows_a = [{"ID": 1}, {"ID": 2}]
        rows_b = [{"ID": 3}, {"ID": 4}, {"ID": 5}]
        db = tmp_path / "union_summary.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", rows_a)
        ref_b = create_duckdb_with_rows(db, "b", rows_b)
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process("union-1", {"mode": "by_name"}, context)

        summary = result["output_summary"]
        # row_count_in é dict por handle (input_1, input_2, ...).
        assert summary["row_count_in"] == {"input_1": 2, "input_2": 3}
        assert summary["row_count_out"] == 5
        assert summary["warnings"] == []

    def test_by_position_schemas_distintos_emite_schema_drift(self, tmp_path: Path) -> None:
        rows_a = [{"COL_A": 1, "COL_B": 2}]
        rows_b = [{"X": 9, "Y": 10}]
        db = tmp_path / "union_drift.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", rows_a)
        ref_b = create_duckdb_with_rows(db, "b", rows_b)
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process(
            "union-1", {"mode": "by_position"}, context
        )

        assert "schema_drift" in result["output_summary"]["warnings"]

    def test_by_position_schemas_iguais_sem_warning(self, tmp_path: Path) -> None:
        rows_a = [{"X": 1, "Y": 2}]
        rows_b = [{"X": 3, "Y": 4}]
        db = tmp_path / "union_no_drift.duckdb"
        ref_a = create_duckdb_with_rows(db, "a", rows_a)
        ref_b = create_duckdb_with_rows(db, "b", rows_b)
        context = make_union_context([("node-a", ref_a), ("node-b", ref_b)])

        result = UnionNodeProcessor().process(
            "union-1", {"mode": "by_position"}, context
        )

        assert "schema_drift" not in result["output_summary"]["warnings"]
