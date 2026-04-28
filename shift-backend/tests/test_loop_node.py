"""
Testes do no ``loop`` — iteracao sobre dataset invocando sub-workflow.

Como o processor depende de ``_invoke_subworkflow`` (que toca o DB via
``async_session_factory``), os testes monkeypatcham essa funcao para
devolver resultados determinados — focando na logica do loop em si:
politicas de erro, paralelismo, guards e transporte de inputs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.services.workflow.nodes import loop as loop_mod
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.nodes.loop import LoopProcessor, validate_loop_inline_bodies

from tests.conftest import create_duckdb_with_rows


def _base_config(
    *,
    source_field: str = "upstream_results.src.data",
    mode: str = "sequential",
    on_item_error: str = "fail_fast",
    **overrides: Any,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "source_field": source_field,
        "workflow_id": str(uuid4()),
        "workflow_version": 1,
        "item_param_name": "item",
        "mode": mode,
        "on_item_error": on_item_error,
        "output_field": "loop_result",
    }
    cfg.update(overrides)
    return cfg


def _ctx_with_list(items: list[Any]) -> dict[str, Any]:
    return {
        "upstream_results": {"src": {"output_field": "data", "data": items}},
        "call_stack": [],
    }


def _ctx_with_duckdb(db_path: Path, table: str) -> dict[str, Any]:
    return {
        "upstream_results": {
            "src": {
                "output_field": "data",
                "data": {
                    "storage_type": "duckdb",
                    "database_path": str(db_path),
                    "table_name": table,
                    "dataset_name": None,
                },
            }
        },
        "call_stack": [],
    }


def _install_invoke_mock(monkeypatch, impl):
    """Substitui _invoke_subworkflow no modulo loop."""
    monkeypatch.setattr(loop_mod, "_invoke_subworkflow", impl)


# ---------------------------------------------------------------------------
# 1. Sequencial sobre DuckDB — itens entregues em ordem
# ---------------------------------------------------------------------------

class TestSequentialOverDuckDb:
    def test_iterates_in_order_and_passes_item_and_index(self, tmp_path: Path, monkeypatch) -> None:
        db_path = tmp_path / "src.duckdb"
        create_duckdb_with_rows(
            db_path,
            "payload",
            [{"id": i, "label": f"r{i}"} for i in range(1, 11)],
        )

        seen: list[tuple[int, dict]] = []

        async def fake_invoke(**kwargs):
            inputs = kwargs["mapped_inputs"]
            seen.append((inputs["idx"], inputs["item"]))
            return {"version": 1, "workflow_output": {"echoed": inputs["item"]["id"]}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_duckdb(db_path, "payload")
        cfg = _base_config(index_param_name="idx")

        result = LoopProcessor().process("loop1", cfg, ctx)

        assert result["iterations"] == 10
        assert result["successes"] == 10
        assert [i for i, _ in seen] == list(range(10))  # ordem preservada
        assert [item["id"] for _, item in seen] == list(range(1, 11))
        assert [r["echoed"] for r in result["loop_result"]["items"]] == list(range(1, 11))


# ---------------------------------------------------------------------------
# 2. Paralelo respeita max_parallelism
# ---------------------------------------------------------------------------

class TestParallelRespectsMax:
    def test_never_exceeds_max_concurrent(self, monkeypatch) -> None:
        concurrent = 0
        peak = 0

        async def fake_invoke(**kwargs):
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1
            return {"version": 1, "workflow_output": {"ok": True}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"i": i} for i in range(20)])
        cfg = _base_config(mode="parallel", max_parallelism=3)

        result = LoopProcessor().process("loop1", cfg, ctx)
        assert result["iterations"] == 20
        assert peak <= 3


# ---------------------------------------------------------------------------
# 3. fail_fast interrompe no primeiro erro
# ---------------------------------------------------------------------------

class TestFailFast:
    def test_raises_on_first_error(self, monkeypatch) -> None:
        calls: list[int] = []

        async def fake_invoke(**kwargs):
            calls.append(kwargs["mapped_inputs"]["item"]["i"])
            if kwargs["mapped_inputs"]["item"]["i"] == 2:
                raise RuntimeError("boom na linha 2")
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"i": i} for i in range(10)])
        cfg = _base_config(mode="sequential", on_item_error="fail_fast")

        with pytest.raises(NodeProcessingError, match="boom na linha 2"):
            LoopProcessor().process("loop1", cfg, ctx)

        # Parou em i=2 — nao deve ter tentado i=3..9 em sequencial.
        assert max(calls) == 2


# ---------------------------------------------------------------------------
# 4. continue: falhas silenciosas, so sucessos aparecem
# ---------------------------------------------------------------------------

class TestContinueMode:
    def test_skips_errors_silently(self, monkeypatch) -> None:
        async def fake_invoke(**kwargs):
            i = kwargs["mapped_inputs"]["item"]["i"]
            if i in (1, 3):
                raise RuntimeError(f"fail_{i}")
            return {"version": 1, "workflow_output": {"i": i}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"i": i} for i in range(5)])
        cfg = _base_config(on_item_error="continue")

        result = LoopProcessor().process("loop1", cfg, ctx)
        assert result["iterations"] == 5
        assert result["successes"] == 3
        assert result["failures"] == 2
        assert [r["i"] for r in result["loop_result"]["items"]] == [0, 2, 4]


# ---------------------------------------------------------------------------
# 5. collect: retorna successes + failures
# ---------------------------------------------------------------------------

class TestCollectMode:
    def test_returns_partial_lists(self, monkeypatch) -> None:
        async def fake_invoke(**kwargs):
            i = kwargs["mapped_inputs"]["item"]["i"]
            if i % 2 == 1:
                raise RuntimeError(f"odd_{i}")
            return {"version": 1, "workflow_output": {"i": i}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"i": i} for i in range(4)])
        cfg = _base_config(on_item_error="collect")

        result = LoopProcessor().process("loop1", cfg, ctx)
        payload = result["loop_result"]
        assert [s["i"] for s in payload["successes"]] == [0, 2]
        assert {f["index"] for f in payload["failures"]} == {1, 3}
        assert all("odd_" in f["error"] for f in payload["failures"])


# ---------------------------------------------------------------------------
# 6. max_iterations guard
# ---------------------------------------------------------------------------

class TestMaxIterationsGuard:
    def test_list_exceeds_max_is_rejected(self, monkeypatch) -> None:
        async def fake_invoke(**kwargs):
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"i": i} for i in range(50)])
        cfg = _base_config(max_iterations=10)

        with pytest.raises(NodeProcessingError, match="max_iterations=10"):
            LoopProcessor().process("loop1", cfg, ctx)

    def test_duckdb_exceeds_max_is_rejected(self, tmp_path: Path, monkeypatch) -> None:
        db_path = tmp_path / "big.duckdb"
        create_duckdb_with_rows(
            db_path, "big", [{"i": i} for i in range(20)]
        )

        async def fake_invoke(**kwargs):
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_duckdb(db_path, "big")
        cfg = _base_config(max_iterations=5)

        with pytest.raises(NodeProcessingError, match="max_iterations=5"):
            LoopProcessor().process("loop1", cfg, ctx)


# ---------------------------------------------------------------------------
# 7. Loop aninhado detectado via context['in_loop']
# ---------------------------------------------------------------------------

class TestNestedLoopDetected:
    def test_in_loop_flag_rejects(self, monkeypatch) -> None:
        async def fake_invoke(**kwargs):
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"i": 1}])
        ctx["in_loop"] = True  # como se estivessemos ja dentro de outro loop
        cfg = _base_config()

        with pytest.raises(NodeProcessingError, match="aninhados"):
            LoopProcessor().process("loop1", cfg, ctx)


# ---------------------------------------------------------------------------
# 8. Dataset vazio nao falha
# ---------------------------------------------------------------------------

class TestEmptySourceReturnsEmpty:
    def test_empty_list(self, monkeypatch) -> None:
        invoked: list[Any] = []

        async def fake_invoke(**kwargs):
            invoked.append(kwargs)
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([])
        cfg = _base_config()

        result = LoopProcessor().process("loop1", cfg, ctx)
        assert result["iterations"] == 0
        assert result["loop_result"]["items"] == []
        assert invoked == []  # nunca chamou o sub-workflow


# ---------------------------------------------------------------------------
# 9. Dataset "grande" materializado em chunks (streaming via DuckDB)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 10. Resolução de source_field — formato legado e novo ParameterValue
# ---------------------------------------------------------------------------


class TestParameterValueResolution:
    """Garante compatibilidade entre o formato legado (string) e o novo (dict ParameterValue)."""

    def test_legacy_upstream_results_string(self, monkeypatch) -> None:
        """Formato legado 'upstream_results.src.data' continua funcionando."""
        seen: list[Any] = []

        async def fake_invoke(**kwargs):
            seen.append(kwargs["mapped_inputs"]["item"])
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"val": 1}, {"val": 2}])
        cfg = _base_config(source_field="upstream_results.src.data")
        result = LoopProcessor().process("loop-legacy", cfg, ctx)
        assert result["iterations"] == 2

    def test_legacy_upstream_alias(self, monkeypatch) -> None:
        """Alias 'upstream.src.data' também é aceito."""
        async def fake_invoke(**kwargs):
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"x": 99}])
        cfg = _base_config(source_field="upstream.src.data")
        result = LoopProcessor().process("loop-alias", cfg, ctx)
        assert result["iterations"] == 1

    def test_new_dynamic_pv_dict(self, monkeypatch) -> None:
        """Novo formato {'mode': 'dynamic', 'template': '{{src.data}}'} funciona."""
        async def fake_invoke(**kwargs):
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_list([{"a": 1}, {"a": 2}, {"a": 3}])
        cfg = _base_config(source_field={"mode": "dynamic", "template": "{{src.data}}"})
        result = LoopProcessor().process("loop-pv-new", cfg, ctx)
        assert result["iterations"] == 3

    def test_legacy_nested_path(self, monkeypatch, tmp_path: Path) -> None:
        """'upstream_results.src.data' resolve referência DuckDB aninhada."""
        db_path = tmp_path / "nested.duckdb"
        create_duckdb_with_rows(db_path, "rows", [{"n": i} for i in range(5)])
        ctx = _ctx_with_duckdb(db_path, "rows")

        count = 0

        async def fake_invoke(**kwargs):
            nonlocal count
            count += 1
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        cfg = _base_config(source_field="upstream_results.src.data")
        result = LoopProcessor().process("loop-nested", cfg, ctx)
        assert result["iterations"] == 5
        assert count == 5


class TestLargeDatasetStreams:
    def test_chunks_through_1500_rows(self, tmp_path: Path, monkeypatch) -> None:
        """Com _CHUNK_SIZE=1000, 1500 linhas exigem mais de 1 chunk."""
        db_path = tmp_path / "big.duckdb"
        create_duckdb_with_rows(
            db_path, "rows", [{"n": i} for i in range(1500)]
        )

        count = 0

        async def fake_invoke(**kwargs):
            nonlocal count
            count += 1
            return {"version": 1, "workflow_output": {}}

        _install_invoke_mock(monkeypatch, fake_invoke)

        ctx = _ctx_with_duckdb(db_path, "rows")
        cfg = _base_config(max_iterations=2000)

        result = LoopProcessor().process("loop1", cfg, ctx)
        assert result["iterations"] == 1500
        assert count == 1500


# ---------------------------------------------------------------------------
# Modo inline: corpo embutido (body_mode='inline')
# ---------------------------------------------------------------------------


_DEFAULT_INLINE_NODES = [{"id": "noop", "type": "stub", "data": {}}]


def _inline_config(
    *,
    body_nodes: list[dict[str, Any]] | None = None,
    body_edges: list[dict[str, Any]] | None = None,
    source_field: str = "upstream_results.src.data",
    mode: str = "sequential",
    on_item_error: str = "fail_fast",
    output_mapping: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "body_mode": "inline",
        "source_field": source_field,
        "body": {
            "nodes": body_nodes if body_nodes is not None else list(_DEFAULT_INLINE_NODES),
            "edges": body_edges if body_edges is not None else [],
        },
        "mode": mode,
        "on_item_error": on_item_error,
        "output_field": "loop_result",
    }
    if output_mapping is not None:
        cfg["output_mapping"] = output_mapping
    cfg.update(overrides)
    return cfg


def _install_inline_mock(monkeypatch, impl):
    """Substitui _invoke_inline_body para isolar do dynamic_runner."""
    monkeypatch.setattr(loop_mod, "_invoke_inline_body", impl)


class TestInlineModeBasics:
    def test_passes_item_and_idx_to_inline_body(self, monkeypatch) -> None:
        seen: list[tuple[int, dict[str, Any], dict[str, Any]]] = []

        async def fake_inline(**kwargs):
            seen.append(
                (kwargs["idx"], kwargs["item"], kwargs["mapped_inputs"])
            )
            return {"echoed": kwargs["item"]["i"], "_idx": kwargs["idx"]}

        _install_inline_mock(monkeypatch, fake_inline)

        ctx = _ctx_with_list([{"i": i} for i in range(4)])
        cfg = _inline_config()

        result = LoopProcessor().process("loop-inline", cfg, ctx)
        assert result["iterations"] == 4
        assert result["successes"] == 4
        assert [s[0] for s in seen] == [0, 1, 2, 3]
        assert [s[1]["i"] for s in seen] == [0, 1, 2, 3]
        assert [r["echoed"] for r in result["loop_result"]["items"]] == [0, 1, 2, 3]

    def test_inline_requires_body_with_nodes(self, monkeypatch) -> None:
        ctx = _ctx_with_list([{"i": 0}])
        cfg = _inline_config(body_nodes=[])
        with pytest.raises(NodeProcessingError, match="body.nodes"):
            LoopProcessor().process("loop-inline", cfg, ctx)

    def test_inline_rejects_invalid_body_type(self, monkeypatch) -> None:
        ctx = _ctx_with_list([{"i": 0}])
        cfg = _inline_config()
        cfg["body"] = "not-a-dict"
        with pytest.raises(NodeProcessingError, match="body"):
            LoopProcessor().process("loop-inline", cfg, ctx)


class TestInlineModeFailFast:
    def test_aborts_on_first_inline_error(self, monkeypatch) -> None:
        calls: list[int] = []

        async def fake_inline(**kwargs):
            i = kwargs["item"]["i"]
            calls.append(i)
            if i == 2:
                raise RuntimeError("boom inline")
            return {"i": i}

        _install_inline_mock(monkeypatch, fake_inline)

        ctx = _ctx_with_list([{"i": i} for i in range(5)])
        cfg = _inline_config(mode="sequential", on_item_error="fail_fast")

        with pytest.raises(NodeProcessingError, match="boom inline"):
            LoopProcessor().process("loop-inline", cfg, ctx)

        assert max(calls) == 2


class TestInlineModeCollect:
    def test_collects_successes_and_failures(self, monkeypatch) -> None:
        async def fake_inline(**kwargs):
            i = kwargs["item"]["i"]
            if i % 2 == 1:
                raise RuntimeError(f"odd_{i}")
            return {"i": i}

        _install_inline_mock(monkeypatch, fake_inline)

        ctx = _ctx_with_list([{"i": i} for i in range(6)])
        cfg = _inline_config(on_item_error="collect")

        result = LoopProcessor().process("loop-inline", cfg, ctx)
        assert result["iterations"] == 6
        assert result["successes"] == 3
        assert result["failures"] == 3
        payload = result["loop_result"]
        assert [r["i"] for r in payload["successes"]] == [0, 2, 4]
        assert {f["index"] for f in payload["failures"]} == {1, 3, 5}


class TestInlineModeParallel:
    def test_parallel_respects_max_in_inline(self, monkeypatch) -> None:
        concurrent = 0
        peak = 0

        async def fake_inline(**kwargs):
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1
            return {"i": kwargs["item"]["i"]}

        _install_inline_mock(monkeypatch, fake_inline)

        ctx = _ctx_with_list([{"i": i} for i in range(15)])
        cfg = _inline_config(mode="parallel", max_parallelism=3)

        result = LoopProcessor().process("loop-inline", cfg, ctx)
        assert result["iterations"] == 15
        assert peak <= 3


class TestInlineModeReceivesContext:
    def test_passes_resolved_connections_and_call_stack(self, monkeypatch) -> None:
        captured: dict[str, Any] = {}

        async def fake_inline(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        _install_inline_mock(monkeypatch, fake_inline)

        conns = {"conn-1": "postgres://stub"}
        ctx = _ctx_with_list([{"i": 0}])
        ctx["_resolved_connections"] = conns
        ctx["call_stack"] = ["wf-A"]
        ctx["vars"] = {"X": 1}

        cfg = _inline_config(output_mapping={"value": "{{item.i}}"})
        result = LoopProcessor().process("loop-inline", cfg, ctx)

        assert result["iterations"] == 1
        # call_stack e parent_context sao repassados ao inline body.
        assert captured["call_stack"] == ["wf-A"]
        assert captured["parent_context"]["_resolved_connections"] == conns
        assert captured["output_mapping"] == {"value": "{{item.i}}"}


# ---------------------------------------------------------------------------
# Validacao estrutural pre-publicacao: validate_loop_inline_bodies
# ---------------------------------------------------------------------------


def _wrap_loop(body_nodes, body_edges, *, body_mode="inline") -> dict[str, Any]:
    """Embrulha um body inline em uma definition com 1 nó loop."""
    return {
        "nodes": [
            {
                "id": "loop-1",
                "type": "loop",
                "data": {
                    "type": "loop",
                    "body_mode": body_mode,
                    "body": {"nodes": body_nodes, "edges": body_edges},
                    "source_field": "upstream_results.x.data",
                },
            }
        ],
        "edges": [],
    }


class TestInlineBodyStaticValidation:
    def test_accepts_valid_body(self) -> None:
        defn = _wrap_loop(
            [
                {"id": "h", "type": "http_request", "data": {"type": "http_request"}},
                {"id": "m", "type": "mapper", "data": {"type": "mapper"}},
            ],
            [{"source": "h", "target": "m"}],
        )
        assert validate_loop_inline_bodies(defn) == []

    def test_rejects_empty_body_nodes(self) -> None:
        defn = _wrap_loop([], [])
        errs = validate_loop_inline_bodies(defn)
        assert any("body.nodes" in e for e in errs)

    def test_rejects_nested_loop_in_body(self) -> None:
        defn = _wrap_loop(
            [{"id": "inner", "type": "loop", "data": {"type": "loop"}}],
            [],
        )
        errs = validate_loop_inline_bodies(defn)
        assert any("loop" in e and "proibido" in e for e in errs)

    def test_rejects_trigger_in_body(self) -> None:
        defn = _wrap_loop(
            [
                {
                    "id": "t",
                    "type": "manual_trigger",
                    "data": {"type": "manual_trigger"},
                }
            ],
            [],
        )
        errs = validate_loop_inline_bodies(defn)
        assert any("manual_trigger" in e and "proibido" in e for e in errs)

    def test_rejects_workflow_input_in_body(self) -> None:
        defn = _wrap_loop(
            [
                {
                    "id": "w",
                    "type": "workflow_input",
                    "data": {"type": "workflow_input"},
                }
            ],
            [],
        )
        errs = validate_loop_inline_bodies(defn)
        assert any("workflow_input" in e for e in errs)

    def test_rejects_edges_crossing_boundary(self) -> None:
        defn = _wrap_loop(
            [{"id": "h", "type": "http_request", "data": {"type": "http_request"}}],
            [{"source": "h", "target": "outside-id"}],
        )
        errs = validate_loop_inline_bodies(defn)
        assert any("fora do body inline" in e for e in errs)

    def test_rejects_duplicate_child_ids(self) -> None:
        defn = _wrap_loop(
            [
                {"id": "x", "type": "mapper", "data": {"type": "mapper"}},
                {"id": "x", "type": "filter", "data": {"type": "filter"}},
            ],
            [],
        )
        errs = validate_loop_inline_bodies(defn)
        assert any("duplicado" in e for e in errs)

    def test_skips_external_loops_silently(self) -> None:
        # Modo external nao precisa de body; validador deve ignorar.
        defn = _wrap_loop([], [], body_mode="external")
        assert validate_loop_inline_bodies(defn) == []
