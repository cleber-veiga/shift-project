"""
Smoke tests para o orquestrador nativo (asyncio) do Shift.

Cobre as funcoes puras do ``dynamic_runner`` que nao dependem de banco
nem de processors reais — garantindo que a migracao do Prefect nao
regrediu a logica de grafo, ordenacao topologica ou branch skipping.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import app.orchestration.flows.dynamic_runner as runner_mod
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
from app.services.workflow.nodes.exceptions import NodeProcessingError


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


class TestRunWorkflowOnErrorBranch:
    @pytest.mark.asyncio
    async def test_on_error_branch_activated_on_failure(self, monkeypatch) -> None:
        seen_upstream: dict[str, Any] = {}
        events: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            events.append(evt)

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            if node_id == "n1":
                raise NodeProcessingError("falha de validacao")
            seen_upstream.update(context.get("upstream_results", {}))
            return {"status": "success", "recovered": True}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {"id": "n1", "type": "mapper", "data": {"type": "mapper", "label": "Origem"}},
                {"id": "n2", "type": "mapper", "data": {"type": "mapper", "label": "Fallback"}},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "on_error"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-on-error",
            execution_id="exec-on-error",
            event_sink=sink,
        )

        assert result["status"] == "completed"
        assert result["node_results"]["n1"]["status"] == "handled_error"
        assert result["node_results"]["n1"]["active_handle"] == "on_error"
        assert seen_upstream["n1"]["status"] == "handled_error"
        assert seen_upstream["n1"]["active_handle"] == "on_error"

        n1_exec = next(evt for evt in result["node_executions"] if evt["node_id"] == "n1")
        assert n1_exec["status"] == "handled_error"
        assert any(evt["type"] == "node_error_handled" for evt in events)

    @pytest.mark.asyncio
    async def test_on_error_branch_absent_preserves_old_behavior(self, monkeypatch) -> None:
        executed: list[str] = []

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            executed.append(node_id)
            if node_id == "n1":
                raise NodeProcessingError("boom")
            return {"status": "success"}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {"id": "n1", "type": "mapper", "data": {"type": "mapper"}},
                {"id": "n2", "type": "mapper", "data": {"type": "mapper"}},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "success"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-old-behavior",
            execution_id="exec-old-behavior",
        )

        assert result["status"] == "failed"
        assert result["failed_by"] == "n1"
        assert executed == ["n1"]

    @pytest.mark.asyncio
    async def test_success_default_handle_skips_on_error_branch(self, monkeypatch) -> None:
        executed: list[str] = []

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            executed.append(node_id)
            return {"status": "success", "node": node_id}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {"id": "n1", "type": "mapper", "data": {"type": "mapper"}},
                {"id": "n2", "type": "mapper", "data": {"type": "mapper"}},
                {"id": "n3", "type": "mapper", "data": {"type": "mapper"}},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "success"},
                {"source": "n1", "target": "n3", "sourceHandle": "on_error"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-success-default",
            execution_id="exec-success-default",
        )

        assert result["status"] == "completed"
        assert result["node_results"]["n1"]["active_handle"] == "success"
        assert executed == ["n1", "n2"]
        n3_exec = next(evt for evt in result["node_executions"] if evt["node_id"] == "n3")
        assert n3_exec["status"] == "skipped"
        assert n3_exec["output_summary"] == {"reason": "skipped_by_branch"}


class TestRetryExhaustedTriggersOnErrorBranch:
    """Integracao retry_policy + on_error branch no workflow real.

    Os componentes isolados (``_run_with_retry`` e on_error) sao cobertos
    em ``test_retry_policy.py`` e em ``TestRunWorkflowOnErrorBranch``.
    Esta classe cobre o encontro deles no ``run_workflow``: a ordem
    esperada e "retry primeiro ate esgotar -> se ainda falha, on_error
    decide". Os testes usam ``backoff_strategy='none'`` para nao dormir.
    """

    @pytest.mark.asyncio
    async def test_retry_exhausted_activates_on_error_branch(self, monkeypatch) -> None:
        """Retry esgotado + edge on_error -> branch on_error ativa.

        Cenario: n1 tem retry_policy (max_attempts=3) e edge on_error
        para n2. O fake sempre falha com NodeProcessingError. Esperado:
        n1 e tentado 3 vezes, workflow nao derruba, n2 roda como
        fallback e recebe o resultado handled_error como upstream.
        """
        attempt_count = 0
        events: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            events.append(evt)

        seen_upstream: dict[str, Any] = {}

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal attempt_count
            if node_id == "n1":
                attempt_count += 1
                raise NodeProcessingError("falha simulada")
            seen_upstream.update(context.get("upstream_results", {}))
            return {"status": "success", "fallback": True}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "mapper",
                    "data": {
                        "type": "mapper",
                        "label": "Fonte",
                        "retry_policy": {
                            "max_attempts": 3,
                            "backoff_strategy": "none",
                            "backoff_seconds": 0.1,
                            "retry_on": [],
                        },
                    },
                },
                {
                    "id": "n2",
                    "type": "mapper",
                    "data": {"type": "mapper", "label": "Fallback"},
                },
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "on_error"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-retry-on-error",
            execution_id="exec-retry-on-error",
            event_sink=sink,
        )

        assert attempt_count == 3, "retry policy deve tentar todas as 3 vezes antes de desistir"
        assert result["status"] == "completed"
        n1_result = result["node_results"]["n1"]
        assert n1_result["status"] == "handled_error"
        assert n1_result["active_handle"] == "on_error"
        assert "falha simulada" in str(n1_result.get("error", ""))

        # n2 (fallback) deve ter executado com n1 como upstream handled_error
        assert "n2" in result["node_results"]
        n2_exec = next(evt for evt in result["node_executions"] if evt["node_id"] == "n2")
        assert n2_exec["status"] == "success"
        assert seen_upstream["n1"]["status"] == "handled_error"
        assert seen_upstream["n1"]["active_handle"] == "on_error"

        # Eventos: >=2 node_retry (apos tentativas 1 e 2) e 1 node_error_handled
        retry_events = [e for e in events if e.get("type") == "node_retry"]
        error_handled_events = [e for e in events if e.get("type") == "node_error_handled"]
        assert len(retry_events) >= 2
        assert all(e["node_id"] == "n1" for e in retry_events)
        assert len(error_handled_events) == 1
        assert error_handled_events[0]["node_id"] == "n1"

    @pytest.mark.asyncio
    async def test_retry_exhausted_without_on_error_edge_fails_workflow(
        self, monkeypatch
    ) -> None:
        """Sem edge on_error, retry esgotado derruba workflow como antes.

        Garantia de backward-compat: workflow antigo (sem edge on_error)
        que ganhou retry_policy continua falhando quando retry esgota,
        em vez de silenciar o erro.
        """
        attempt_count = 0

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal attempt_count
            if node_id == "n1":
                attempt_count += 1
                raise NodeProcessingError("falha simulada")
            return {"status": "success"}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "mapper",
                    "data": {
                        "type": "mapper",
                        "retry_policy": {
                            "max_attempts": 3,
                            "backoff_strategy": "none",
                            "backoff_seconds": 0.1,
                        },
                    },
                },
                {"id": "n2", "type": "mapper", "data": {"type": "mapper"}},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "success"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-retry-no-on-error",
            execution_id="exec-retry-no-on-error",
        )

        assert attempt_count == 3, "retry deve executar todas as tentativas"
        assert result["status"] == "failed"
        assert result["failed_by"] == "n1"
        assert "falha simulada" in str(result.get("error", ""))

    @pytest.mark.asyncio
    async def test_retry_succeeds_before_exhaustion_skips_on_error(
        self, monkeypatch
    ) -> None:
        """Retry que sucede antes de esgotar nao ativa on_error.

        Happy path: n1 falha na 1a e sucede na 2a tentativa. A edge
        on_error existe, mas nao deve ser ativada; n2 (fallback) fica
        como ``skipped_by_branch``.
        """
        attempt_count = 0
        events: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            events.append(evt)

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal attempt_count
            if node_id == "n1":
                attempt_count += 1
                if attempt_count == 1:
                    raise NodeProcessingError("falha transiente")
                return {"status": "success", "recovered_on_attempt": attempt_count}
            return {"status": "success"}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "mapper",
                    "data": {
                        "type": "mapper",
                        "retry_policy": {
                            "max_attempts": 3,
                            "backoff_strategy": "none",
                            "backoff_seconds": 0.1,
                        },
                    },
                },
                {"id": "n2", "type": "mapper", "data": {"type": "mapper"}},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "on_error"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-retry-success",
            execution_id="exec-retry-success",
            event_sink=sink,
        )

        assert attempt_count == 2, "deve parar assim que a tentativa 2 sucede"
        assert result["status"] == "completed"
        n1_result = result["node_results"]["n1"]
        assert n1_result["status"] == "success"
        assert n1_result.get("active_handle") != "on_error"

        # n2 (conectado via on_error) deve ter sido pulado pelo branch
        n2_exec = next(evt for evt in result["node_executions"] if evt["node_id"] == "n2")
        assert n2_exec["status"] == "skipped"
        assert n2_exec["output_summary"] == {"reason": "skipped_by_branch"}

        # Nenhum node_error_handled deve ter sido emitido.
        error_handled_events = [e for e in events if e.get("type") == "node_error_handled"]
        assert error_handled_events == []

    @pytest.mark.asyncio
    async def test_retry_on_filter_non_matching_triggers_on_error_immediately(
        self, monkeypatch
    ) -> None:
        """retry_on sem match: 1 tentativa apenas, mas on_error ainda ativa.

        Filtro ``retry_on=['timeout']`` nao casa com "erro de validacao".
        O runner nao deve tentar de novo, mas como a edge on_error existe,
        o branch ativa em vez de derrubar o workflow.
        """
        attempt_count = 0

        async def fake_execute_registered_node(
            node_id: str,
            node_type: str,
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal attempt_count
            if node_id == "n1":
                attempt_count += 1
                raise NodeProcessingError("erro de validacao no payload")
            return {"status": "success", "fallback": True}

        monkeypatch.setattr(runner_mod, "execute_registered_node", fake_execute_registered_node)

        payload = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "mapper",
                    "data": {
                        "type": "mapper",
                        "retry_policy": {
                            "max_attempts": 5,
                            "backoff_strategy": "none",
                            "backoff_seconds": 0.1,
                            "retry_on": ["timeout"],
                        },
                    },
                },
                {"id": "n2", "type": "mapper", "data": {"type": "mapper"}},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "sourceHandle": "on_error"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-retry-filter",
            execution_id="exec-retry-filter",
        )

        assert attempt_count == 1, "filtro retry_on sem match nao deve disparar retry"
        assert result["status"] == "completed"
        n1_result = result["node_results"]["n1"]
        assert n1_result["status"] == "handled_error"
        assert n1_result["active_handle"] == "on_error"
        n2_exec = next(evt for evt in result["node_executions"] if evt["node_id"] == "n2")
        assert n2_exec["status"] == "success"


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


# ---------------------------------------------------------------------------
# run_workflow — event_sink (observabilidade em tempo real)
# ---------------------------------------------------------------------------

class TestRunWorkflowEventSink:
    """Verifica a superficie de eventos emitida pelo runner quando
    ``event_sink`` e fornecido. Usada pelo ``workflow_test_service`` para
    alimentar a stream SSE."""

    @staticmethod
    def _make_sink() -> tuple[list[dict[str, Any]], Any]:
        collected: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            collected.append(evt)

        return collected, sink

    @pytest.mark.asyncio
    async def test_no_sink_means_backward_compat(self) -> None:
        """Sem ``event_sink``, o runner nao deve ter overhead nem mudar shape."""
        result = await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-bc",
            execution_id="exec-bc",
        )
        assert result["status"] == "completed"
        assert "node_results" in result
        assert "node_executions" in result

    @pytest.mark.asyncio
    async def test_empty_workflow_emits_start_and_end(self) -> None:
        events, sink = self._make_sink()
        await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-empty",
            execution_id="exec-empty",
            event_sink=sink,
        )
        types = [e["type"] for e in events]
        assert types == ["execution_start", "execution_end"]
        assert events[0]["execution_id"] == "exec-empty"
        assert events[0]["node_count"] == 0
        assert events[0]["mode"] == "production"
        assert events[-1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_mode_propagated_to_start_event(self) -> None:
        events, sink = self._make_sink()
        await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-mode",
            execution_id="exec-mode",
            event_sink=sink,
            mode="test",
        )
        assert events[0]["mode"] == "test"

    @pytest.mark.asyncio
    async def test_unknown_node_emits_node_skipped(self) -> None:
        """No sem processor dispara ``node_skipped`` com reason=unknown_type."""
        events, sink = self._make_sink()
        payload = {
            "nodes": [
                {"id": "n1", "type": "inexistente", "data": {"label": "X"}},
            ],
            "edges": [],
        }
        await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-skip",
            execution_id="exec-skip",
            event_sink=sink,
        )
        types = [e["type"] for e in events]
        assert "node_skipped" in types
        skipped = next(e for e in events if e["type"] == "node_skipped")
        assert skipped["node_id"] == "n1"
        assert skipped["node_type"] == "inexistente"
        assert skipped["label"] == "X"
        assert skipped["reason"] == "unknown_type"
        # execution_end deve vir por ultimo
        assert events[-1]["type"] == "execution_end"

    @pytest.mark.asyncio
    async def test_event_payload_shape_is_consistent(self) -> None:
        events, sink = self._make_sink()
        await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-shape",
            execution_id="exec-shape",
            event_sink=sink,
        )
        # Toda mensagem tem as chaves minimas.
        for evt in events:
            assert "type" in evt
            assert "timestamp" in evt
            assert evt.get("execution_id") == "exec-shape"

    @pytest.mark.asyncio
    async def test_sink_exception_does_not_kill_workflow(self) -> None:
        """Exceptions do sink sao capturadas — observabilidade nao derruba execucao."""

        async def bad_sink(evt: dict[str, Any]) -> None:
            raise RuntimeError("sink boom")

        result = await run_workflow(
            workflow_payload={"nodes": [], "edges": []},
            workflow_id="wf-bad-sink",
            execution_id="exec-bad-sink",
            event_sink=bad_sink,
        )
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_end_status_reflects_cancel(self) -> None:
        """CancelledError faz execution_end ser ``cancelled`` (via finally)."""
        captured: list[dict[str, Any]] = []
        started = asyncio.Event()

        async def sink(evt: dict[str, Any]) -> None:
            captured.append(evt)
            # Bloqueia o primeiro emit (execution_start) para dar janela
            # a task ser cancelada antes de completar naturalmente.
            if evt["type"] == "execution_start":
                started.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(
            run_workflow(
                workflow_payload={"nodes": [], "edges": []},
                workflow_id="wf-cancel",
                execution_id="exec-cancel",
                event_sink=sink,
            )
        )
        await started.wait()  # garante que entramos no sink antes de cancelar
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # execution_end deve ter sido emitido no finally com status=cancelled.
        assert any(
            e["type"] == "execution_end" and e.get("status") == "cancelled"
            for e in captured
        )


# ---------------------------------------------------------------------------
# run_workflow — pinnedOutput / enabled=False
# ---------------------------------------------------------------------------

class TestRunWorkflowPinnedOutput:
    """``data.pinnedOutput`` faz passthrough sem chamar processor."""

    @pytest.mark.asyncio
    async def test_pinned_output_short_circuits_processor(self) -> None:
        """O runner nao deve tentar executar um no com pinnedOutput.

        Usamos ``type=inexistente`` sem processor registrado — se o runner
        tentasse rodar, emitiria ``node_skipped`` com reason=unknown_type.
        Com pinnedOutput, o resultado deve ser o dict fixado.
        """
        pinned = {"row_count": 2, "rows": [{"a": 1}, {"a": 2}], "columns": ["a"]}
        payload = {
            "nodes": [{
                "id": "n1",
                "type": "inexistente",
                "data": {"label": "Pinned", "pinnedOutput": pinned},
            }],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-pin",
            execution_id="exec-pin",
        )
        assert result["status"] == "completed"
        assert result["node_results"]["n1"] == pinned

    @pytest.mark.asyncio
    async def test_pinned_output_records_node_execution_as_skipped(self) -> None:
        """Registro em DB: status=skipped, output_summary={is_pinned: True}."""
        pinned = {"row_count": 1, "rows": [{"x": 1}]}
        payload = {
            "nodes": [{
                "id": "n1",
                "type": "whatever",
                "data": {"label": "P", "pinnedOutput": pinned},
            }],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-pin2",
            execution_id="exec-pin2",
        )
        events = result["node_executions"]
        assert len(events) == 1
        evt = events[0]
        assert evt["status"] == "skipped"
        assert evt["output_summary"] == {"is_pinned": True}
        assert evt["row_count_out"] == 1

    @pytest.mark.asyncio
    async def test_pinned_output_emits_node_complete_with_is_pinned(self) -> None:
        """SSE: evento node_complete leva is_pinned=True e o output cru."""
        pinned = {"row_count": 3, "rows": [{"i": i} for i in range(3)]}
        collected: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            collected.append(evt)

        payload = {
            "nodes": [{
                "id": "n1",
                "type": "whatever",
                "data": {"pinnedOutput": pinned},
            }],
            "edges": [],
        }
        await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-pin3",
            execution_id="exec-pin3",
            event_sink=sink,
        )
        complete = next(e for e in collected if e["type"] == "node_complete")
        assert complete["is_pinned"] is True
        assert complete["output"] == pinned
        # Pinned nao emite node_start — so node_complete.
        assert not any(
            e["type"] == "node_start" and e["node_id"] == "n1" for e in collected
        )

    @pytest.mark.asyncio
    async def test_pinned_output_flows_to_downstream(self) -> None:
        """Downstream deve receber o pinnedOutput como upstream real."""
        pinned = {"row_count": 1, "rows": [{"a": 42}]}
        payload = {
            "nodes": [
                {"id": "n1", "type": "whatever", "data": {"pinnedOutput": pinned}},
                {"id": "n2", "type": "inexistente", "data": {}},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-pin-down",
            execution_id="exec-pin-down",
        )
        # n1 tem o pinnedOutput, n2 (sem processor) e skipped por unknown_type
        # mas NAO por skipped_by_branch — seu upstream esta ativo.
        assert result["node_results"]["n1"] == pinned
        # n2 nao e registrado em node_results (sem processor), mas aparece em
        # node_executions com status=skipped e reason=unknown_type (nao disabled).
        n2_evt = next(e for e in result["node_executions"] if e["node_id"] == "n2")
        assert n2_evt["status"] == "skipped"
        assert n2_evt["output_summary"]["reason"] == "unknown_type"

    @pytest.mark.asyncio
    async def test_empty_pinned_output_not_used(self) -> None:
        """``pinnedOutput = {}`` (falsy) nao curto-circuita — deve executar."""
        payload = {
            "nodes": [{
                "id": "n1",
                "type": "inexistente",
                "data": {"pinnedOutput": {}},
            }],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-pin-empty",
            execution_id="exec-pin-empty",
        )
        # Sem pinnedOutput efetivo, cai no caminho unknown_type.
        evt = result["node_executions"][0]
        assert evt["output_summary"]["reason"] == "unknown_type"


class TestRunWorkflowDisabledNode:
    """``data.enabled is False`` pula o no e propaga skip downstream."""

    @pytest.mark.asyncio
    async def test_disabled_node_is_not_executed(self) -> None:
        """No desativado nao gera entrada em ``node_results`` (exceto o skip)."""
        payload = {
            "nodes": [{
                "id": "n1",
                "type": "inexistente",
                "data": {"label": "Off", "enabled": False},
            }],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-off",
            execution_id="exec-off",
        )
        assert result["status"] == "completed"
        n1_result = result["node_results"]["n1"]
        assert n1_result["status"] == "skipped"
        assert n1_result["reason"] == "disabled"

    @pytest.mark.asyncio
    async def test_disabled_records_as_skipped(self) -> None:
        payload = {
            "nodes": [{
                "id": "n1",
                "type": "whatever",
                "data": {"enabled": False},
            }],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-off2",
            execution_id="exec-off2",
        )
        evt = result["node_executions"][0]
        assert evt["status"] == "skipped"
        assert evt["output_summary"] == {"reason": "disabled"}

    @pytest.mark.asyncio
    async def test_disabled_emits_node_skipped_event(self) -> None:
        collected: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            collected.append(evt)

        payload = {
            "nodes": [{
                "id": "n1",
                "type": "whatever",
                "data": {"label": "X", "enabled": False},
            }],
            "edges": [],
        }
        await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-off3",
            execution_id="exec-off3",
            event_sink=sink,
        )
        skipped = next(e for e in collected if e["type"] == "node_skipped")
        assert skipped["node_id"] == "n1"
        assert skipped["reason"] == "disabled"
        assert skipped["label"] == "X"

    @pytest.mark.asyncio
    async def test_disabled_propagates_skip_to_downstream(self) -> None:
        """Descendente de no desativado recebe ``skipped_by_branch``."""
        payload = {
            "nodes": [
                {"id": "n1", "type": "whatever", "data": {"enabled": False}},
                {"id": "n2", "type": "whatever", "data": {}},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-off-down",
            execution_id="exec-off-down",
        )
        assert result["node_results"]["n1"]["reason"] == "disabled"
        # n2 deve ter sido pulado em cascata (todas as entradas inativas).
        n2_evt = next(e for e in result["node_executions"] if e["node_id"] == "n2")
        assert n2_evt["status"] == "skipped"
        assert n2_evt["output_summary"]["reason"] == "skipped_by_branch"

    @pytest.mark.asyncio
    async def test_enabled_true_executes_normally(self) -> None:
        """``enabled=True`` (explicito) nao deve pular."""
        payload = {
            "nodes": [{
                "id": "n1",
                "type": "inexistente",
                "data": {"enabled": True},
            }],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-on",
            execution_id="exec-on",
        )
        # Sem processor, cai em unknown_type (nao em disabled).
        evt = result["node_executions"][0]
        assert evt["output_summary"]["reason"] == "unknown_type"

    @pytest.mark.asyncio
    async def test_enabled_missing_defaults_to_enabled(self) -> None:
        """``data.enabled`` ausente deve tratar como habilitado."""
        payload = {
            "nodes": [{"id": "n1", "type": "inexistente", "data": {}}],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-default",
            execution_id="exec-default",
        )
        evt = result["node_executions"][0]
        assert evt["output_summary"]["reason"] == "unknown_type"
