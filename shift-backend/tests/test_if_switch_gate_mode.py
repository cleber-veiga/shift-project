"""
Testes do gate mode em IfNodeProcessor e SwitchNodeProcessor.

Gate mode e ativado automaticamente quando o upstream primario e um
dict de metadata/status (ex: resultado de truncate_table) e nenhum
upstream expoe ref DuckDB. Nesse modo, o no avalia as condicoes contra
o proprio dict e ativa EXATAMENTE UM handle.

Os testes tambem verificam que o modo row-partition original continua
funcionando quando ha ref DuckDB real no upstream.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pytest

from app.services.workflow.nodes.if_node import IfNodeProcessor
from app.services.workflow.nodes.switch_node import SwitchNodeProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_duckdb_ref(tmpdir: str) -> dict[str, Any]:
    """Cria um banco DuckDB real com uma tabela de 2 linhas."""
    db_path = Path(tmpdir) / "test.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE src AS "
            "SELECT 1 AS id, 'a' AS name UNION ALL SELECT 2, 'b'"
        )
    finally:
        conn.close()
    return {
        "storage_type": "duckdb",
        "database_path": str(db_path),
        "table_name": "src",
        "dataset_name": None,
    }


# ---------------------------------------------------------------------------
# IfNodeProcessor — gate mode
# ---------------------------------------------------------------------------

class TestIfNodeGateMode:
    def test_gate_passes_activates_true_handle(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success", "target_table": "t", "rows_affected": 42}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "conditions": [
                {"field": "status", "operator": "eq", "value": "success"}
            ],
            "logic": "and",
        }

        result = processor.process("if-1", config, context)

        assert result["status"] == "completed"
        assert result["gate_mode"] is True
        assert result["active_handles"] == ["true"]
        assert result["true_count"] == 1
        assert result["false_count"] == 0
        assert result["row_count"] == 1
        # Branches fazem passthrough do upstream
        assert result["branches"]["true"] is upstream
        assert result["branches"]["false"] is upstream

    def test_gate_fails_activates_false_handle(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "error", "target_table": "t"}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "conditions": [
                {"field": "status", "operator": "eq", "value": "success"}
            ]
        }

        result = processor.process("if-2", config, context)

        assert result["gate_mode"] is True
        assert result["active_handles"] == ["false"]
        assert result["true_count"] == 0
        assert result["false_count"] == 1

    def test_gate_logic_and_all_must_pass(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success", "rows_affected": 42}
        context = {"upstream_results": {"trunc-1": upstream}}
        # Primeira passa, segunda falha
        config = {
            "conditions": [
                {"field": "status", "operator": "eq", "value": "success"},
                {"field": "rows_affected", "operator": "gt", "value": 100},
            ],
            "logic": "and",
        }

        result = processor.process("if-3", config, context)

        assert result["active_handles"] == ["false"]

    def test_gate_logic_or_any_passes(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success", "rows_affected": 42}
        context = {"upstream_results": {"trunc-1": upstream}}
        # Primeira passa, segunda falha — com OR, passa
        config = {
            "conditions": [
                {"field": "status", "operator": "eq", "value": "success"},
                {"field": "rows_affected", "operator": "gt", "value": 100},
            ],
            "logic": "or",
        }

        result = processor.process("if-4", config, context)

        assert result["active_handles"] == ["true"]
        assert result["true_count"] == 1

    def test_gate_missing_field_is_null_passes(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success"}  # sem "error_code"
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "conditions": [
                {"field": "error_code", "operator": "is_null", "value": None}
            ]
        }

        result = processor.process("if-5", config, context)

        assert result["active_handles"] == ["true"]

    def test_gate_missing_field_eq_fails(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success"}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "conditions": [
                {"field": "error_code", "operator": "eq", "value": "OK"}
            ]
        }

        result = processor.process("if-6", config, context)

        assert result["active_handles"] == ["false"]
        assert result["false_count"] == 1

    def test_gate_contains_and_in_operators(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success", "message": "Operation completed OK"}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "conditions": [
                {"field": "message", "operator": "contains", "value": "completed"},
                {"field": "status", "operator": "in",
                 "value": ["success", "ok"]},
            ],
            "logic": "and",
        }

        result = processor.process("if-7", config, context)

        assert result["active_handles"] == ["true"]

    def test_gate_no_conditions_defaults_to_true(self) -> None:
        processor = IfNodeProcessor()
        upstream = {"status": "success"}
        context = {"upstream_results": {"trunc-1": upstream}}
        config: dict[str, Any] = {"conditions": []}

        result = processor.process("if-8", config, context)

        assert result["gate_mode"] is True
        assert result["active_handles"] == ["true"]


# ---------------------------------------------------------------------------
# IfNodeProcessor — row-partition preserva comportamento original
# ---------------------------------------------------------------------------

class TestIfNodeRowPartitionStillWorks:
    def test_row_partition_with_real_duckdb_ref(self, tmp_path: Path) -> None:
        tmpdir = str(tmp_path)
        ref = _make_duckdb_ref(tmpdir)
        context = {
            "execution_id": "exec-1",
            "upstream_results": {"prev": ref},
        }
        config = {
            "conditions": [{"field": "id", "operator": "eq", "value": 1}]
        }

        processor = IfNodeProcessor()
        result = processor.process("if-rp", config, context)

        # Sem gate_mode em row-partition
        assert result.get("gate_mode") is not True
        assert result["status"] == "completed"
        assert result["true_count"] == 1
        assert result["false_count"] == 1
        assert set(result["active_handles"]) == {"true", "false"}
        # Branches apontam para tabelas materializadas
        assert result["branches"]["true"]["storage_type"] == "duckdb"
        assert result["branches"]["true"]["table_name"].endswith("_true")


# ---------------------------------------------------------------------------
# SwitchNodeProcessor — gate mode
# ---------------------------------------------------------------------------

class TestSwitchNodeGateMode:
    def test_gate_matches_case_activates_its_handle(self) -> None:
        processor = SwitchNodeProcessor()
        upstream = {"status": "success", "target_table": "t"}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "switch_field": "status",
            "cases": [
                {"label": "ok", "values": ["success"]},
                {"label": "ko", "values": ["error"]},
            ],
        }

        result = processor.process("sw-1", config, context)

        assert result["status"] == "completed"
        assert result["gate_mode"] is True
        assert result["active_handles"] == ["ok"]
        assert result["ok_count"] == 1
        assert result["ko_count"] == 0
        assert result["default_count"] == 0
        assert result["row_count"] == 1
        # Todos os handles presentes em branches (passthrough)
        assert result["branches"]["ok"] is upstream
        assert result["branches"]["ko"] is upstream
        assert result["branches"]["default"] is upstream

    def test_gate_no_case_matches_falls_to_default(self) -> None:
        processor = SwitchNodeProcessor()
        upstream = {"status": "pending"}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "switch_field": "status",
            "cases": [
                {"label": "ok", "values": ["success"]},
                {"label": "ko", "values": ["error"]},
            ],
        }

        result = processor.process("sw-2", config, context)

        assert result["gate_mode"] is True
        assert result["active_handles"] == ["default"]
        assert result["default_count"] == 1
        assert result["ok_count"] == 0
        assert result["ko_count"] == 0

    def test_gate_missing_field_falls_to_default(self) -> None:
        processor = SwitchNodeProcessor()
        upstream = {"target_table": "t"}  # sem "status"
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "switch_field": "status",
            "cases": [{"label": "ok", "values": ["success"]}],
        }

        result = processor.process("sw-3", config, context)

        assert result["active_handles"] == ["default"]
        assert result["default_count"] == 1

    def test_gate_trims_value_before_matching(self) -> None:
        processor = SwitchNodeProcessor()
        upstream = {"status": "  success  "}
        context = {"upstream_results": {"trunc-1": upstream}}
        config = {
            "switch_field": "status",
            "cases": [{"label": "ok", "values": ["success"]}],
        }

        result = processor.process("sw-4", config, context)

        assert result["active_handles"] == ["ok"]
        assert result["ok_count"] == 1


# ---------------------------------------------------------------------------
# SwitchNodeProcessor — row-partition preserva comportamento original
# ---------------------------------------------------------------------------

class TestSwitchNodeRowPartitionStillWorks:
    def test_row_partition_with_real_duckdb_ref(self, tmp_path: Path) -> None:
        tmpdir = str(tmp_path)
        ref = _make_duckdb_ref(tmpdir)
        context = {
            "execution_id": "exec-1",
            "upstream_results": {"prev": ref},
        }
        config = {
            "switch_field": "name",
            "cases": [
                {"label": "alpha", "values": ["a"]},
                {"label": "beta", "values": ["b"]},
            ],
        }

        processor = SwitchNodeProcessor()
        result = processor.process("sw-rp", config, context)

        assert result.get("gate_mode") is not True
        assert result["status"] == "completed"
        assert result["alpha_count"] == 1
        assert result["beta_count"] == 1
        assert result["default_count"] == 0
        assert set(result["active_handles"]) == {"alpha", "beta"}
        assert result["branches"]["alpha"]["storage_type"] == "duckdb"
        assert result["branches"]["alpha"]["table_name"].endswith("_alpha")
