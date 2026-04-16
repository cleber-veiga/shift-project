"""
Testes do SwitchNodeProcessor com row-partition via DuckDB.

Valida que:
- Linhas sao distribuidas em N buckets nomeados conforme ``switch_field``.
- Linhas nao casadas caem em ``default``.
- ``branches`` contem referencias DuckDB por handle (label do case + default).
- ``active_handles`` lista apenas ramos nao vazios.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.workflow.nodes.switch_node import SwitchNodeProcessor
from tests.conftest import make_context, read_duckdb_table


def _run_switch(
    db_path: Path,
    table_name: str,
    switch_field: str,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    processor = SwitchNodeProcessor()
    context = make_context(db_path, table_name)
    config = {"switch_field": switch_field, "cases": cases}
    return processor.process("sw-1", config, context)


class TestSwitchNodeRowPartition:
    def test_distributes_rows_to_matching_cases(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_switch(
            db_path,
            "source_data",
            "PRODUTO",
            [
                {"label": "moveis", "values": ["CADEIRA", "MESA", "SOFA"]},
                {"label": "iluminacao", "values": ["LAMPADA"]},
            ],
        )
        assert result["status"] == "completed"
        assert result["moveis_count"] == 3
        assert result["iluminacao_count"] == 1
        assert result["default_count"] == 0
        assert set(result["active_handles"]) == {"moveis", "iluminacao"}

        moveis_rows = read_duckdb_table(
            str(db_path), result["branches"]["moveis"]["table_name"]
        )
        iluminacao_rows = read_duckdb_table(
            str(db_path), result["branches"]["iluminacao"]["table_name"]
        )
        assert {r["PRODUTO"] for r in moveis_rows} == {"CADEIRA", "MESA", "SOFA"}
        assert {r["PRODUTO"] for r in iluminacao_rows} == {"LAMPADA"}

    def test_unmatched_rows_go_to_default(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_switch(
            db_path,
            "source_data",
            "PRODUTO",
            [{"label": "moveis", "values": ["CADEIRA", "MESA"]}],
        )
        assert result["moveis_count"] == 2
        assert result["default_count"] == 2
        assert set(result["active_handles"]) == {"moveis", "default"}

        default_rows = read_duckdb_table(
            str(db_path), result["branches"]["default"]["table_name"]
        )
        assert {r["PRODUTO"] for r in default_rows} == {"SOFA", "LAMPADA"}

    def test_empty_case_branch_excluded_from_active(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        # 'vazio' nao casa com nenhum registro
        result = _run_switch(
            db_path,
            "source_data",
            "PRODUTO",
            [
                {"label": "vazio", "values": ["INEXISTENTE"]},
                {"label": "cheio", "values": ["CADEIRA", "MESA", "SOFA", "LAMPADA"]},
            ],
        )
        assert "vazio" not in result["active_handles"]
        assert "cheio" in result["active_handles"]
        assert "default" not in result["active_handles"]

    def test_no_switch_field_all_go_to_default(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_switch(db_path, "source_data", "", [])
        assert result["default_count"] == 4
        assert result["active_handles"] == ["default"]

    def test_numeric_values_casted_to_string(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        # Compara coluna inteira NUMERO_NOTA com valores-string
        result = _run_switch(
            db_path,
            "source_data",
            "NUMERO_NOTA",
            [{"label": "nota_1001", "values": ["1001"]}],
        )
        assert result["nota_1001_count"] == 2

    def test_case_without_values_produces_empty_bucket(self, duckdb_with_sample):
        db_path, _ = duckdb_with_sample
        result = _run_switch(
            db_path,
            "source_data",
            "PRODUTO",
            [
                {"label": "vazio", "values": []},
                {"label": "cadeira", "values": ["CADEIRA"]},
            ],
        )
        assert result["vazio_count"] == 0
        assert result["cadeira_count"] == 1
        # As 3 linhas restantes vao para default
        assert result["default_count"] == 3
