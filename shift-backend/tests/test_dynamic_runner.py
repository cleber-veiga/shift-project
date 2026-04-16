"""
Smoke tests para o orquestrador nativo (asyncio) do Shift.

Cobre as funcoes puras do ``dynamic_runner`` que nao dependem de banco
nem de processors reais — garantindo que a migracao do Prefect nao
regrediu a logica de grafo, ordenacao topologica ou branch skipping.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.orchestration.flows.dynamic_runner import (
    _build_graph,
    _extract_row_counts,
    _get_node_type,
    _is_node_skipped,
    _resolve_node_timeout,
    _route_upstream_result,
    _summarize_result,
    _topological_sort_levels,
    run_workflow,
)


# ---------------------------------------------------------------------------
# _resolve_node_timeout
# ---------------------------------------------------------------------------

class TestResolveNodeTimeout:
    def test_defaults_when_absent(self) -> None:
        assert _resolve_node_timeout({}) == 300

    def test_explicit_int(self) -> None:
        assert _resolve_node_timeout({"timeout_seconds": 60}) == 60.0

    def test_explicit_float(self) -> None:
        assert _resolve_node_timeout({"timeout_seconds": 12.5}) == 12.5

    @pytest.mark.parametrize("value", [0, -1, -10, "60", None, True, False])
    def test_invalid_falls_back_to_default(self, value: Any) -> None:
        assert _resolve_node_timeout({"timeout_seconds": value}) == 300


# ---------------------------------------------------------------------------
# _build_graph / _topological_sort_levels
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_linear_chain(self) -> None:
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]
        adj, reverse, in_deg, node_map, _, _ = _build_graph(nodes, edges)

        assert adj == {"a": ["b"], "b": ["c"]}
        assert reverse == {"b": ["a"], "c": ["b"]}
        assert in_deg == {"a": 0, "b": 1, "c": 1}
        assert set(node_map) == {"a", "b", "c"}

    def test_diamond_topology_three_levels(self) -> None:
        # a -> b -> d
        # a -> c -> d
        nodes = [{"id": nid} for nid in ("a", "b", "c", "d")]
        edges = [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
            {"source": "b", "target": "d"},
            {"source": "c", "target": "d"},
        ]
        _, _, in_deg, _, _, _ = _build_graph(nodes, edges)
        # Copia antes de passar: _topological_sort_levels muta in_degree.
        levels = _topological_sort_levels(dict(in_deg), {
            "a": ["b", "c"],
            "b": ["d"],
            "c": ["d"],
        })
        assert levels[0] == ["a"]
        assert sorted(levels[1]) == ["b", "c"]
        assert levels[2] == ["d"]

    def test_edge_handles_captured(self) -> None:
        nodes = [{"id": "src"}, {"id": "dst"}]
        edges = [{
            "source": "src",
            "target": "dst",
            "sourceHandle": "true",
            "targetHandle": "left",
        }]
        _, _, _, _, edge_handles, target_handles = _build_graph(nodes, edges)
        assert edge_handles[("src", "dst")] == "true"
        assert target_handles[("src", "dst")] == "left"

    def test_edge_handles_accept_snake_case(self) -> None:
        """React Flow usa camelCase, mas aceitamos snake_case como fallback."""
        nodes = [{"id": "src"}, {"id": "dst"}]
        edges = [{
            "source": "src",
            "target": "dst",
            "source_handle": "false",
            "target_handle": "right",
        }]
        _, _, _, _, edge_handles, target_handles = _build_graph(nodes, edges)
        assert edge_handles[("src", "dst")] == "false"
        assert target_handles[("src", "dst")] == "right"


# ---------------------------------------------------------------------------
# _is_node_skipped (branch cascading)
# ---------------------------------------------------------------------------

class TestIsNodeSkipped:
    def test_root_never_skipped(self) -> None:
        assert _is_node_skipped("root", {}, set(), set()) is False

    def test_one_active_source_not_skipped(self) -> None:
        reverse = {"x": ["a", "b"]}
        # b ativo -> nao skip
        assert _is_node_skipped("x", reverse, {"a"}, set()) is False

    def test_all_sources_skipped_marks_skipped(self) -> None:
        reverse = {"x": ["a", "b"]}
        assert _is_node_skipped("x", reverse, {"a", "b"}, set()) is True

    def test_all_edges_inactive_marks_skipped(self) -> None:
        reverse = {"x": ["a", "b"]}
        inactive = {("a", "x"), ("b", "x")}
        assert _is_node_skipped("x", reverse, set(), inactive) is True

    def test_mixed_skip_and_inactive(self) -> None:
        reverse = {"x": ["a", "b"]}
        # a foi skipped; aresta b->x foi inativada => tudo inativo
        assert _is_node_skipped("x", reverse, {"a"}, {("b", "x")}) is True


# ---------------------------------------------------------------------------
# _get_node_type
# ---------------------------------------------------------------------------

class TestGetNodeType:
    def test_from_top_level_type(self) -> None:
        assert _get_node_type({"type": "sqlDatabase"}) == "sqlDatabase"

    def test_fallback_to_data_type(self) -> None:
        assert _get_node_type({"data": {"type": "aggregator"}}) == "aggregator"

    def test_unknown_returns_literal(self) -> None:
        assert _get_node_type({}) == "unknown"


# ---------------------------------------------------------------------------
# _route_upstream_result — roteamento row-partition por sourceHandle
# ---------------------------------------------------------------------------

class TestRouteUpstreamResult:
    def test_passthrough_when_no_branches(self) -> None:
        """Sem branches, o resultado deve ser retornado intacto."""
        source_result = {"node_id": "a", "status": "completed", "data": "x"}
        assert _route_upstream_result(source_result, "any") is source_result

    def test_passthrough_when_no_source_handle(self) -> None:
        """Sem sourceHandle na aresta, nao ha como rotear — retorna intacto."""
        branches = {
            "true": {"storage_type": "duckdb", "database_path": "/tmp/x", "table_name": "t"},
            "false": {"storage_type": "duckdb", "database_path": "/tmp/x", "table_name": "f"},
        }
        source_result = {"branches": branches}
        assert _route_upstream_result(source_result, None) is source_result

    def test_substitutes_branch_ref_when_handle_matches(self) -> None:
        """Com sourceHandle, substitui a referencia primaria pela do ramo."""
        true_ref = {
            "storage_type": "duckdb",
            "database_path": "/tmp/x.duckdb",
            "table_name": "node1_true",
        }
        false_ref = {
            "storage_type": "duckdb",
            "database_path": "/tmp/x.duckdb",
            "table_name": "node1_false",
        }
        source_result = {
            "node_id": "node1",
            "status": "completed",
            "branches": {"true": true_ref, "false": false_ref},
            "active_handles": ["true", "false"],
        }

        routed = _route_upstream_result(source_result, "true")
        assert routed is not source_result
        assert routed["data"] == true_ref
        assert routed["output_field"] == "data"

        routed_false = _route_upstream_result(source_result, "false")
        assert routed_false["data"] == false_ref

    def test_passthrough_when_handle_not_in_branches(self) -> None:
        """sourceHandle que nao existe em branches -> passthrough sem erro."""
        source_result = {
            "branches": {
                "true": {"storage_type": "duckdb", "database_path": "/tmp/x", "table_name": "t"},
            }
        }
        # 'default' nao existe -> retorna intacto (sem levantar)
        assert _route_upstream_result(source_result, "default") is source_result

    def test_non_dict_source_result_is_returned_unchanged(self) -> None:
        assert _route_upstream_result("not-a-dict", "true") == "not-a-dict"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# run_workflow — smoke tests do entrypoint
# ---------------------------------------------------------------------------

class TestRunWorkflowSmoke:
    @pytest.mark.asyncio
    async def test_empty_payload_completes(self) -> None:
        """Payload vazio -> status completed, sem resultados."""
        result = await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-empty",
            execution_id="exec-empty",
        )
        assert result["status"] == "completed"
        assert result["node_results"] == {}
        assert result["node_executions"] == []

    @pytest.mark.asyncio
    async def test_unknown_node_type_is_tolerated(self) -> None:
        """No de tipo desconhecido e apenas logado; workflow completa vazio."""
        payload = {
            "nodes": [
                {"id": "n1", "type": "totallyUnknownNodeType", "data": {}},
            ],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-unknown",
            execution_id="exec-unknown",
        )
        assert result["status"] == "completed"
        # Nao ha processor -> nao ha entrada de resultado.
        assert result["node_results"] == {}

    @pytest.mark.asyncio
    async def test_requires_payload_or_id(self) -> None:
        """Sem payload e sem workflow_id, o runner deve falhar rapido."""
        with pytest.raises(ValueError, match="workflow_payload ou workflow_id"):
            await run_workflow()


# ---------------------------------------------------------------------------
# _extract_row_counts — heuristicas de contagem para persistencia
# ---------------------------------------------------------------------------

class TestExtractRowCounts:
    def test_non_dict_returns_none_pair(self) -> None:
        assert _extract_row_counts("not-a-dict") == (None, None)

    def test_empty_dict(self) -> None:
        assert _extract_row_counts({}) == (None, None)

    def test_row_count_as_fallback_for_both(self) -> None:
        """``row_count`` vale para in e out quando nao ha campos especificos."""
        assert _extract_row_counts({"row_count": 42}) == (42, 42)

    def test_total_input_overrides_row_count_for_in(self) -> None:
        assert _extract_row_counts({"total_input": 10, "row_count": 7}) == (10, 7)

    def test_rows_written_overrides_row_count_for_out(self) -> None:
        """Load nodes: rows_written e a saida efetiva gravada."""
        assert _extract_row_counts({"row_count": 10, "rows_written": 9}) == (10, 9)

    def test_row_partition_sums_true_false_for_out(self) -> None:
        assert _extract_row_counts({"true_count": 3, "false_count": 5}) == (None, 8)

    def test_boolean_not_treated_as_int(self) -> None:
        """bool e subclasse de int — mas True==1 nao deve virar contagem."""
        assert _extract_row_counts({"row_count": True}) == (None, None)


# ---------------------------------------------------------------------------
# _summarize_result — resumo seguro para JSONB
# ---------------------------------------------------------------------------

class TestSummarizeResult:
    def test_non_dict_wraps_as_value(self) -> None:
        summary = _summarize_result("ok")
        assert summary == {"value": "ok"}

    def test_drops_heavy_top_level_keys(self) -> None:
        summary = _summarize_result({
            "status": "success",
            "rows": [{"a": 1}, {"a": 2}],
            "data": {"storage_type": "duckdb", "table_name": "x"},
            "upstream_results": {"foo": "bar"},
            "row_count": 2,
        })
        assert "rows" not in summary
        assert "data" not in summary
        assert "upstream_results" not in summary
        assert summary["status"] == "success"
        assert summary["row_count"] == 2

    def test_strips_nested_rows_in_dict_value(self) -> None:
        summary = _summarize_result({
            "result": {"row_count": 3, "rows": [{"a": 1}]},
        })
        assert summary["result"] == {"row_count": 3}

    def test_truncates_long_lists(self) -> None:
        summary = _summarize_result({"items": list(range(50))})
        assert summary["items"] == {"_truncated": True, "length": 50}


# ---------------------------------------------------------------------------
# run_workflow — emissao de node_executions (per-node persistence events)
# ---------------------------------------------------------------------------

class TestRunWorkflowNodeExecutions:
    @pytest.mark.asyncio
    async def test_empty_payload_emits_empty_list(self) -> None:
        """Payload vazio -> ``node_executions`` presente como lista vazia."""
        result = await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-empty",
            execution_id="exec-empty",
        )
        assert result["node_executions"] == []

    @pytest.mark.asyncio
    async def test_unknown_type_emits_skipped_event(self) -> None:
        """No sem processor registrado emite evento com status=skipped."""
        payload = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "totallyUnknownType",
                    "data": {"label": "Nó misterioso"},
                },
            ],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-unknown",
            execution_id="exec-unknown",
        )
        events = result["node_executions"]
        assert len(events) == 1
        evt = events[0]
        assert evt["node_id"] == "n1"
        assert evt["status"] == "skipped"
        assert evt["node_type"] == "totallyUnknownType"
        assert evt["label"] == "Nó misterioso"
        assert evt["output_summary"] == {
            "reason": "unknown_type",
            "node_type": "totallyUnknownType",
        }
        assert evt["started_at"] is not None
        assert evt["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_event_falls_back_to_type_when_no_label(self) -> None:
        payload = {
            "nodes": [{"id": "n1", "type": "mysteryType", "data": {}}],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-no-label",
            execution_id="exec-no-label",
        )
        assert result["node_executions"][0]["label"] == "mysteryType"
