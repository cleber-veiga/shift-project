"""
Testes para StrategyObserver (modo passivo, Fase 4).
"""

from __future__ import annotations

import pytest

from app.orchestration.flows.strategy_observer import (
    StrategyDecision,
    build_strategy_sse_event,
    observe_strategy,
)


class TestObserveStrategy:

    def test_disabled_sempre_skip(self) -> None:
        d = observe_strategy("n1", "filter", {}, is_disabled=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "disabled"

    def test_pinned_sempre_skip(self) -> None:
        d = observe_strategy("n1", "filter", {}, is_pinned=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "pinned_output"

    def test_checkpoint_skip(self) -> None:
        d = observe_strategy("n1", "filter", {}, is_checkpoint=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "checkpoint_restored"

    def test_cache_hit_skip(self) -> None:
        d = observe_strategy("n1", "sql_database", {}, is_cache_hit=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "cache_hit"

    def test_output_node_sempre_roda(self) -> None:
        d = observe_strategy("n1", "loadNode", {})
        assert d.should_run is True
        assert d.reason == "output_node"

    def test_io_node_io_thread(self) -> None:
        d = observe_strategy("n1", "sql_database", {})
        assert d.should_run is True
        assert d.strategy == "io_thread"
        assert d.reason == "io_node"

    def test_control_node_local_thread(self) -> None:
        d = observe_strategy("n1", "ifElse", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"
        assert d.reason == "control_node"

    def test_narrow_node_local_thread(self) -> None:
        d = observe_strategy("n1", "filter", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"
        assert d.reason == "narrow_default"

    def test_wide_heavy_data_worker(self) -> None:
        d = observe_strategy("n1", "join", {})
        assert d.should_run is True
        assert d.strategy == "data_worker"
        assert d.reason == "wide_heavy"

    def test_wide_light_local_thread(self) -> None:
        d = observe_strategy("n1", "sort", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"
        assert d.reason == "wide_default"

    def test_tipo_desconhecido_fallback(self) -> None:
        """Tipos desconhecidos não devem levantar exceção."""
        d = observe_strategy("n1", "nao_existe_xyz", {})
        assert isinstance(d, StrategyDecision)

    def test_prioridade_disabled_sobre_output(self) -> None:
        """disabled tem prioridade sobre output_node."""
        d = observe_strategy("n1", "loadNode", {}, is_disabled=True)
        assert d.should_run is False
        assert d.strategy == "skip"


class TestBuildStrategySseEvent:

    def test_shape_evento(self) -> None:
        decision = StrategyDecision(True, "local_thread", "narrow_default")
        evt = build_strategy_sse_event("n1", "filter", "exec-123", decision, label="Filtro")
        assert evt["type"] == "node_strategy_observed"
        assert evt["node_id"] == "n1"
        assert evt["node_type"] == "filter"
        assert evt["strategy"] == "local_thread"
        assert evt["should_run"] is True
        assert evt["reason"] == "narrow_default"
        assert evt["label"] == "Filtro"
        assert evt["execution_id"] == "exec-123"
