"""
Prova que as duas portas de entrada (cron/manual e SSE) produzem o mesmo
resultado ao final da execucao.

A arquitetura pos-Fase 3 garante isso estruturalmente: ambas passam por
``WorkflowExecutionService._run_and_persist``, que chama
``run_workflow`` (com ou sem ``event_sink``) e depois usa o MESMO
``_persist_final_state`` com ``result["node_executions"]``.

O teste evita dependencia de Postgres/DuckDB rodando o runner direto:
- Chama ``run_workflow(...)`` sem sink (equivalente ao path cron)
- Chama ``run_workflow(..., event_sink=sink)`` (equivalente ao path SSE)
- Afirma: ``result["node_executions"]`` e o mesmo nos dois (modulo
  timestamps), e os eventos emitidos ao sink no segundo caminho
  correspondem aos node_executions.

Como a camada de persistencia consome SO ``result["node_executions"]``,
paridade ali implica paridade nas linhas gravadas em
``workflow_node_executions``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.orchestration.flows.dynamic_runner import run_workflow


def _strip_timestamps(evt: dict[str, Any]) -> dict[str, Any]:
    """Remove campos voláteis de tempo para comparar duas execucoes."""
    return {
        k: v
        for k, v in evt.items()
        if k not in ("started_at", "completed_at", "duration_ms")
    }


def _payload_with_pin_and_unknown() -> dict[str, Any]:
    """Payload com: 1 no pinnedOutput (passthrough) + 1 no tipo desconhecido
    (vira node_skipped) + 1 no filho do pinnedOutput que tambem cai em
    node_skipped (unknown_type). Cobre os tres status que o runner emite."""
    return {
        "nodes": [
            {
                "id": "pin",
                "type": "inexistente",
                "data": {
                    "label": "Pinned",
                    "pinnedOutput": {"row_count": 2, "rows": [{"a": 1}, {"a": 2}]},
                },
            },
            {"id": "unk", "type": "tambem_inexistente", "data": {"label": "Desconhecido"}},
            {"id": "dis", "type": "inexistente", "data": {"label": "Off", "enabled": False}},
        ],
        "edges": [
            {"source": "pin", "target": "unk"},
        ],
    }


class TestParityRunnerResult:
    @pytest.mark.asyncio
    async def test_result_is_identical_with_and_without_sink(self) -> None:
        payload = _payload_with_pin_and_unknown()

        # Cron path (sem sink)
        cron = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-parity",
            execution_id="exec-cron",
        )

        # SSE path (com sink)
        events: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            events.append(evt)

        sse = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-parity",
            execution_id="exec-sse",
            event_sink=sink,
        )

        # Os dois resultados tem o mesmo status e o mesmo conjunto de
        # node_executions modulo timestamps. E o que a camada de
        # persistencia de fato le.
        assert cron["status"] == sse["status"] == "completed"

        cron_execs = [_strip_timestamps(e) for e in cron["node_executions"]]
        sse_execs = [_strip_timestamps(e) for e in sse["node_executions"]]
        assert cron_execs == sse_execs

        # node_results tambem bate (pinnedOutput sobreviveu).
        assert cron["node_results"] == sse["node_results"]

    @pytest.mark.asyncio
    async def test_sink_events_match_node_executions(self) -> None:
        """Os eventos emitidos ao sink refletem os mesmos nos presentes em
        result["node_executions"]."""
        payload = _payload_with_pin_and_unknown()
        events: list[dict[str, Any]] = []

        async def sink(evt: dict[str, Any]) -> None:
            events.append(evt)

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-parity",
            execution_id="exec-x",
            event_sink=sink,
        )

        # Nos presentes no result devem bater com os nos vistos no sink.
        exec_node_ids = {e["node_id"] for e in result["node_executions"]}
        sink_node_ids = {
            e["node_id"]
            for e in events
            if e["type"] in ("node_complete", "node_error", "node_skipped")
            and "node_id" in e
        }
        assert exec_node_ids == sink_node_ids

        # Sink sempre comeca com execution_start e termina com execution_end.
        assert events[0]["type"] == "execution_start"
        assert events[-1]["type"] == "execution_end"
        assert events[-1]["status"] == "completed"


class TestParityTargetNodeId:
    """``target_node_id`` no runner recorta o grafo; o resultado deve conter
    apenas os ancestrais do alvo."""

    @pytest.mark.asyncio
    async def test_target_node_id_filters_descendants(self) -> None:
        # a -> b -> c  (alvo: b)
        payload = {
            "nodes": [
                {"id": "a", "type": "inexistente", "data": {
                    "pinnedOutput": {"row_count": 1, "rows": [{"x": 1}]},
                }},
                {"id": "b", "type": "inexistente", "data": {
                    "pinnedOutput": {"row_count": 1, "rows": [{"x": 2}]},
                }},
                {"id": "c", "type": "inexistente", "data": {
                    "pinnedOutput": {"row_count": 1, "rows": [{"x": 3}]},
                }},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
            ],
        }

        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-t",
            execution_id="exec-t",
            target_node_id="b",
        )
        node_ids = {e["node_id"] for e in result["node_executions"]}
        assert node_ids == {"a", "b"}
        assert "c" not in result["node_results"]

    @pytest.mark.asyncio
    async def test_target_node_id_none_runs_everything(self) -> None:
        payload = {
            "nodes": [
                {"id": "a", "type": "inexistente", "data": {
                    "pinnedOutput": {"row_count": 1, "rows": [{"x": 1}]},
                }},
                {"id": "b", "type": "inexistente", "data": {
                    "pinnedOutput": {"row_count": 1, "rows": [{"x": 2}]},
                }},
            ],
            "edges": [{"source": "a", "target": "b"}],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-t",
            execution_id="exec-t",
            target_node_id=None,
        )
        node_ids = {e["node_id"] for e in result["node_executions"]}
        assert node_ids == {"a", "b"}

    @pytest.mark.asyncio
    async def test_target_node_id_unknown_falls_back_to_full_payload(self) -> None:
        payload = {
            "nodes": [
                {"id": "a", "type": "inexistente", "data": {
                    "pinnedOutput": {"row_count": 1, "rows": [{"x": 1}]},
                }},
            ],
            "edges": [],
        }
        result = await run_workflow(
            workflow_payload=payload,
            workflow_id="wf-t",
            execution_id="exec-t",
            target_node_id="nao-existe",
        )
        node_ids = {e["node_id"] for e in result["node_executions"]}
        assert node_ids == {"a"}
