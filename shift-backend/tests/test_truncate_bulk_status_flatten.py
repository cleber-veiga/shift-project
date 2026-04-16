"""
Verifica que ``truncate_table`` e ``bulk_insert`` expoem o status da
operacao no topo do resultado — paridade com ``workflow_test_service`` —
para que um ``if_node`` downstream possa gate em ``status == "success"``.

Os processadores sao testados com ``load_service`` mockado, sem tocar
em banco real.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.load_service import LoadResult, TruncateResult
from app.services.workflow.nodes.bulk_insert import BulkInsertProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.nodes.truncate_table import TruncateTableProcessor


# ---------------------------------------------------------------------------
# TruncateTableProcessor — top-level status reflete a operacao
# ---------------------------------------------------------------------------

class TestTruncateTableStatusFlatten:
    def test_success_exposes_top_level_status_success(self) -> None:
        """TruncateResult.status='success' deve aparecer no topo do output."""
        processor = TruncateTableProcessor()
        config = {
            "connection_string": "postgresql://u:p@h/db",
            "target_table": "public.clientes",
            "mode": "truncate",
        }
        context: dict[str, Any] = {"upstream_results": {}}

        with patch(
            "app.services.workflow.nodes.truncate_table.load_service.truncate"
        ) as mock_truncate:
            mock_truncate.return_value = TruncateResult(
                status="success",
                target_table="public.clientes",
                mode="truncate",
                rows_affected=42,
            )
            output = processor.process("trunc-1", config, context)

        assert output["status"] == "success"
        assert output["target_table"] == "public.clientes"
        assert output["mode"] == "truncate"
        assert output["rows_affected"] == 42
        # Metadata do runner preservada
        assert output["node_id"] == "trunc-1"
        assert output["output_field"] == "data"

    def test_firebird_raises_node_processing_error(self) -> None:
        processor = TruncateTableProcessor()
        config = {
            "connection_string": "firebird+fdb://u:p@h/db",
            "target_table": "T",
        }
        with pytest.raises(NodeProcessingError, match="Firebird"):
            processor.process("trunc-fb", config, {"upstream_results": {}})

    def test_no_upstream_ref_means_no_data_key(self) -> None:
        """Sem upstream DuckDB, nao deve haver chave ``data`` — apenas status."""
        processor = TruncateTableProcessor()
        config = {
            "connection_string": "postgresql://u:p@h/db",
            "target_table": "t",
        }
        with patch(
            "app.services.workflow.nodes.truncate_table.load_service.truncate"
        ) as mock_truncate:
            mock_truncate.return_value = TruncateResult(
                status="success", target_table="t"
            )
            output = processor.process("trunc-2", config, {"upstream_results": {}})

        assert "data" not in output


# ---------------------------------------------------------------------------
# BulkInsertProcessor — top-level status reflete a operacao
# ---------------------------------------------------------------------------

class TestBulkInsertStatusFlatten:
    def test_no_upstream_returns_skipped_at_top_level(self) -> None:
        """Sem upstream DuckDB e sem linhas lidas -> status=skipped no topo."""
        processor = BulkInsertProcessor()
        config = {
            "connection_string": "postgresql://u:p@h/db",
            "target_table": "imppessoa",
            "column_mapping": [{"source": "A", "target": "A"}],
        }
        context: dict[str, Any] = {"upstream_results": {}}

        # Sem upstream, _read_rows_from_duckdb recebe reference falsa — mockamos.
        with patch(
            "app.services.workflow.nodes.bulk_insert._read_rows_from_duckdb",
            return_value=[],
        ), patch(
            "app.services.workflow.nodes.bulk_insert.get_primary_input_reference",
            return_value={
                "storage_type": "duckdb",
                "database_path": "/tmp/x.duckdb",
                "table_name": "t",
                "dataset_name": None,
            },
        ):
            output = processor.process("bulk-1", config, context)

        assert output["status"] == "skipped"
        assert output["rows_written"] == 0
        assert output["target_table"] == "imppessoa"

    def test_success_exposes_top_level_status_success(self) -> None:
        processor = BulkInsertProcessor()
        config = {
            "connection_string": "postgresql://u:p@h/db",
            "target_table": "imppessoa",
            "column_mapping": [{"source": "A", "target": "A"}],
        }
        context: dict[str, Any] = {"upstream_results": {}}

        with patch(
            "app.services.workflow.nodes.bulk_insert._read_rows_from_duckdb",
            return_value=[{"A": 1}, {"A": 2}],
        ), patch(
            "app.services.workflow.nodes.bulk_insert.get_primary_input_reference",
            return_value={
                "storage_type": "duckdb",
                "database_path": "/tmp/x.duckdb",
                "table_name": "t",
                "dataset_name": None,
            },
        ), patch(
            "app.services.workflow.nodes.bulk_insert.load_service.insert"
        ) as mock_insert:
            mock_insert.return_value = LoadResult(
                status="success",
                rows_received=2,
                rows_written=2,
                target_table="imppessoa",
            )
            output = processor.process("bulk-2", config, context)

        assert output["status"] == "success"
        assert output["rows_written"] == 2
        assert output["target_table"] == "imppessoa"
        # Payload aninhado permanece acessivel via output_field
        assert isinstance(output["load_result"], dict)
        assert output["load_result"]["status"] == "success"

    def test_firebird_raises(self) -> None:
        processor = BulkInsertProcessor()
        config = {
            "connection_string": "firebird+fdb://u:p@h/db",
            "target_table": "t",
            "column_mapping": [{"source": "a", "target": "a"}],
        }
        with pytest.raises(NodeProcessingError, match="Firebird"):
            processor.process("bulk-fb", config, {"upstream_results": {}})
