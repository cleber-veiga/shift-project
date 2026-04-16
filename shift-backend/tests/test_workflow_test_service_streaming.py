"""
Testes da camada SSE do ``workflow_test_service``.

Cobre apenas as transformacoes de apresentacao:
- ``_transform_for_sse``: mapa evento-do-runner -> payload SSE
- ``_trim_for_sse``: corte de ``rows`` em modo producao

A execucao, resolucao de conexoes, filtragem por ``target_node_id`` e
persistencia ficam em ``workflow_service`` / ``dynamic_runner`` e sao
testadas la.
"""

from __future__ import annotations

from app.services.workflow_test_service import (
    _transform_for_sse,
    _trim_for_sse,
)


# ---------------------------------------------------------------------------
# _transform_for_sse — mapeamento runner -> SSE
# ---------------------------------------------------------------------------

class TestTransformForSSEStart:
    def test_execution_start_forwards_node_count_from_runner(self) -> None:
        """O runner ja calcula node_count (com target_node_id aplicado);
        a camada SSE apenas repassa."""
        evt = {
            "type": "execution_start",
            "execution_id": "exec-1",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "node_count": 3,
            "mode": "test",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["type"] == "execution_start"
        assert sse["execution_id"] == "exec-1"
        assert sse["node_count"] == 3
        assert sse["mode"] == "test"
        assert sse["timestamp"] == "2025-01-01T00:00:00+00:00"

    def test_execution_start_node_count_defaults_to_zero(self) -> None:
        evt = {"type": "execution_start", "execution_id": "exec-1", "timestamp": "t"}
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["node_count"] == 0


class TestTransformForSSENodeStart:
    def test_passthrough_shape(self) -> None:
        evt = {
            "type": "node_start",
            "node_id": "n1",
            "node_type": "sql_database",
            "label": "Consulta",
            "timestamp": "t",
            "execution_id": "exec-1",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse == {
            "type": "node_start",
            "node_id": "n1",
            "node_type": "sql_database",
            "label": "Consulta",
            "timestamp": "t",
        }


class TestTransformForSSENodeComplete:
    def test_output_is_trimmed_in_production(self) -> None:
        big_rows = [{"i": i} for i in range(250)]
        evt = {
            "type": "node_complete",
            "node_id": "n1",
            "label": "X",
            "output": {"row_count": 250, "rows": big_rows},
            "duration_ms": 123,
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="production", total_start=0.0)
        assert sse is not None
        assert sse["output"]["is_preview"] is True
        assert sse["output"]["total_rows"] == 250
        assert len(sse["output"]["rows"]) == 100

    def test_output_untouched_in_test_mode(self) -> None:
        big_rows = [{"i": i} for i in range(250)]
        evt = {
            "type": "node_complete",
            "node_id": "n1",
            "label": "X",
            "output": {"row_count": 250, "rows": big_rows},
            "duration_ms": 123,
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert len(sse["output"]["rows"]) == 250
        assert "is_preview" not in sse["output"]

    def test_missing_output_defaults_to_empty_dict(self) -> None:
        evt = {
            "type": "node_complete",
            "node_id": "n1",
            "label": "X",
            "duration_ms": 1,
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["output"] == {}

    def test_is_pinned_preserved(self) -> None:
        evt = {
            "type": "node_complete",
            "node_id": "n1",
            "label": "X",
            "output": {"row_count": 1, "rows": [{"a": 1}]},
            "duration_ms": 0,
            "is_pinned": True,
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["is_pinned"] is True


class TestTransformForSSENodeError:
    def test_passthrough_error_payload(self) -> None:
        evt = {
            "type": "node_error",
            "node_id": "n1",
            "label": "X",
            "error": "Timeout",
            "duration_ms": 60000,
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["type"] == "node_error"
        assert sse["error"] == "Timeout"
        assert sse["duration_ms"] == 60000


class TestTransformForSSENodeSkipped:
    """Compat BC: runner emite node_skipped, SSE envia como node_complete
    com output={status: skipped, reason: ...} para preservar o shape legado."""

    def test_skipped_becomes_node_complete_with_status_skipped(self) -> None:
        evt = {
            "type": "node_skipped",
            "node_id": "n1",
            "label": "X",
            "reason": "skipped_by_branch",
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["type"] == "node_complete"
        assert sse["node_id"] == "n1"
        assert sse["output"] == {"status": "skipped", "reason": "skipped_by_branch"}
        assert sse["duration_ms"] == 0

    def test_skipped_default_reason_when_missing(self) -> None:
        evt = {"type": "node_skipped", "node_id": "n1", "label": "X", "timestamp": "t"}
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["output"] == {"status": "skipped", "reason": "skipped"}


class TestTransformForSSEExecutionEnd:
    def test_end_becomes_execution_complete_with_uppercase_status(self) -> None:
        evt = {
            "type": "execution_end",
            "execution_id": "exec-1",
            "status": "completed",
            "timestamp": "t",
        }
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["type"] == "execution_complete"
        assert sse["execution_id"] == "exec-1"
        assert sse["status"] == "SUCCESS"

    def test_failed_status_maps_to_uppercase_failed(self) -> None:
        evt = {"type": "execution_end", "status": "failed", "timestamp": "t"}
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse is not None
        assert sse["status"] == "FAILED"

    def test_duration_ms_computed_from_total_start(self) -> None:
        import time
        evt = {"type": "execution_end", "status": "completed", "timestamp": "t"}
        sse = _transform_for_sse(
            evt, mode="test", total_start=time.monotonic() - 0.05
        )
        assert sse is not None
        assert isinstance(sse["duration_ms"], int)
        assert sse["duration_ms"] >= 0


class TestTransformForSSEUnknown:
    def test_unknown_event_passes_through(self) -> None:
        """Eventos desconhecidos nao devem ser silenciados — dev observa."""
        evt = {"type": "custom_thing", "foo": "bar"}
        sse = _transform_for_sse(evt, mode="test", total_start=0.0)
        assert sse == evt


# ---------------------------------------------------------------------------
# _trim_for_sse — resumo de output em producao
# ---------------------------------------------------------------------------

class TestTrimForSSE:
    def test_small_output_passthrough(self) -> None:
        out = {"row_count": 3, "rows": [{"a": 1}, {"a": 2}, {"a": 3}]}
        assert _trim_for_sse(out) == out

    def test_large_rows_are_truncated_with_metadata(self) -> None:
        rows = [{"i": i} for i in range(150)]
        out = {"row_count": 150, "rows": rows}
        trimmed = _trim_for_sse(out)
        assert len(trimmed["rows"]) == 100
        assert trimmed["is_preview"] is True
        assert trimmed["total_rows"] == 150

    def test_branches_reference_passthrough(self) -> None:
        """O runner retorna branches como refs DuckDB (sem ``rows``) — trim
        nao deve alterar esse formato."""
        out = {
            "row_count": 10,
            "branches": {
                "true": {
                    "storage_type": "duckdb",
                    "database_path": "/tmp/x.duckdb",
                    "table_name": "n1_true",
                },
                "false": {
                    "storage_type": "duckdb",
                    "database_path": "/tmp/x.duckdb",
                    "table_name": "n1_false",
                },
            },
        }
        assert _trim_for_sse(out) == out

    def test_non_dict_returned_as_is(self) -> None:
        assert _trim_for_sse("not a dict") == "not a dict"  # type: ignore[arg-type]
