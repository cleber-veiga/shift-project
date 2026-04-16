"""
Testes do IfNodeProcessor com row-partition via DuckDB.

Valida que:
- Linhas sao particionadas corretamente em 'true'/'false' conforme a condicao.
- ``branches`` contem referencias DuckDB apontando para tabelas materializadas.
- ``active_handles`` lista apenas os ramos com ao menos 1 linha.
- A logica ``and``/``or`` combina multiplas condicoes.
- Operadores (contains, startswith, gte, in, is_null, etc.) funcionam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.workflow.nodes.if_node import IfNodeProcessor
from tests.conftest import make_context, read_duckdb_table


def _run_if_node(
    db_path: Path,
    table_name: str,
    conditions: list[dict[str, Any]],
    logic: str = "and",
) -> dict[str, Any]:
    processor = IfNodeProcessor()
    context = make_context(db_path, table_name)
    config = {"conditions": conditions, "logic": logic}
    return processor.process("ifn-1", config, context)


class TestIfNodeRowPartition:
    def test_splits_rows_by_eq_condition(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [{"field": "PRODUTO", "operator": "eq", "value": "CADEIRA"}],
        )

        assert result["status"] == "completed"
        assert result["true_count"] == 1
        assert result["false_count"] == 3
        assert set(result["active_handles"]) == {"true", "false"}
        assert "true" in result["branches"]
        assert "false" in result["branches"]

        true_rows = read_duckdb_table(
            str(db_path), result["branches"]["true"]["table_name"]
        )
        false_rows = read_duckdb_table(
            str(db_path), result["branches"]["false"]["table_name"]
        )
        assert {r["PRODUTO"] for r in true_rows} == {"CADEIRA"}
        assert {r["PRODUTO"] for r in false_rows} == {"MESA", "SOFA", "LAMPADA"}

    def test_empty_branch_excluded_from_active_handles(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        # Nenhuma linha casa — true fica vazio
        result = _run_if_node(
            db_path,
            "source_data",
            [{"field": "PRODUTO", "operator": "eq", "value": "INEXISTENTE"}],
        )
        assert result["true_count"] == 0
        assert result["false_count"] == 4
        assert result["active_handles"] == ["false"]

    def test_all_rows_true_branch(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [{"field": "QUANTIDADE", "operator": "gte", "value": 0}],
        )
        assert result["true_count"] == 4
        assert result["false_count"] == 0
        assert result["active_handles"] == ["true"]

    def test_logic_and_combines_conditions(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [
                {"field": "QUANTIDADE", "operator": "gte", "value": 2},
                {"field": "DESCONTO", "operator": "gt", "value": 0},
            ],
            logic="and",
        )
        # MESA (qty=3, desc=10) e LAMPADA (qty=5, desc=5) atendem ambas
        assert result["true_count"] == 2
        assert result["false_count"] == 2

    def test_logic_or_combines_conditions(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [
                {"field": "PRODUTO", "operator": "eq", "value": "CADEIRA"},
                {"field": "PRODUTO", "operator": "eq", "value": "MESA"},
            ],
            logic="or",
        )
        assert result["true_count"] == 2
        assert result["false_count"] == 2

    def test_contains_operator(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [{"field": "PRODUTO", "operator": "contains", "value": "A"}],
        )
        # CADEIRA, MESA, SOFA, LAMPADA — todos contem 'A' (case-insensitive)
        assert result["true_count"] == 4

    def test_in_operator_requires_list(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        with pytest.raises(Exception, match="requer lista"):
            _run_if_node(
                db_path,
                "source_data",
                [{"field": "PRODUTO", "operator": "in", "value": "CADEIRA"}],
            )

    def test_in_operator_with_list(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [
                {
                    "field": "PRODUTO",
                    "operator": "in",
                    "value": ["CADEIRA", "MESA"],
                }
            ],
        )
        assert result["true_count"] == 2

    def test_invalid_logic_raises(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        with pytest.raises(Exception, match="logic deve ser"):
            _run_if_node(
                db_path,
                "source_data",
                [{"field": "PRODUTO", "operator": "eq", "value": "X"}],
                logic="xor",
            )

    def test_no_conditions_sends_all_to_true(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(db_path, "source_data", [])
        assert result["true_count"] == 4
        assert result["false_count"] == 0
        assert result["active_handles"] == ["true"]

    def test_branches_reference_shape(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_if_node(
            db_path,
            "source_data",
            [{"field": "QUANTIDADE", "operator": "gte", "value": 3}],
        )
        true_ref = result["branches"]["true"]
        assert true_ref["storage_type"] == "duckdb"
        assert true_ref["database_path"] == str(db_path)
        assert true_ref["table_name"].endswith("_true")
        assert true_ref["dataset_name"] is None
