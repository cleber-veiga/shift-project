"""
Testes para StrategyResolver (Fase 5) — decisor ativo.

Matriz de cenários conforme critério de aceite do plano:
  - output_node sempre roda
  - force_refresh=True invalida cache
  - cache_hit retorna SKIP
  - cache_miss + node cacheable retorna estratégia padrão
  - nunca rodou retorna estratégia padrão
  - pinned/disabled retorna SKIP
"""

from __future__ import annotations

import pytest

from app.orchestration.flows.strategy_resolver import (
    StrategyDecision,
    build_strategy_sse_event,
    resolve_strategy,
)


# ─── Output node ──────────────────────────────────────────────────────────────

class TestOutputNode:

    def test_output_node_sempre_roda(self) -> None:
        d = resolve_strategy("n1", "loadNode", {})
        assert d.should_run is True
        assert d.reason == "output_node"

    def test_output_node_ignora_cache_hit(self) -> None:
        """Output node roda mesmo com cache_hit=True (é output, nunca skipar)."""
        d = resolve_strategy("n1", "loadNode", {}, is_cache_hit=True)
        assert d.should_run is True
        assert d.reason == "output_node"

    def test_bulk_insert_output_node(self) -> None:
        d = resolve_strategy("n1", "bulk_insert", {})
        assert d.should_run is True
        assert d.reason == "output_node"

    def test_output_node_disabled_priority(self) -> None:
        """disabled tem prioridade sobre output_node."""
        d = resolve_strategy("n1", "loadNode", {}, is_disabled=True)
        assert d.should_run is False
        assert d.strategy == "skip"


# ─── force_refresh invalida cache ─────────────────────────────────────────────

class TestForceRefresh:

    def test_force_refresh_invalida_cache_hit(self) -> None:
        d = resolve_strategy(
            "n1", "sql_database", {},
            is_cache_hit=True,
            force_refresh=True,
        )
        assert d.should_run is True
        assert d.reason == "force_refresh"

    def test_force_refresh_sem_cache_hit(self) -> None:
        d = resolve_strategy("n1", "filter", {}, force_refresh=True)
        assert d.should_run is True
        assert d.reason == "force_refresh"

    def test_force_refresh_tem_prioridade_sobre_cache(self) -> None:
        """force_refresh precede o branch de cache_hit."""
        d = resolve_strategy(
            "n1", "aggregator", {},
            is_cache_hit=True,
            force_refresh=True,
        )
        assert d.should_run is True

    def test_force_refresh_com_disabled_nao_roda(self) -> None:
        """disabled tem prioridade sobre force_refresh."""
        d = resolve_strategy(
            "n1", "filter", {},
            is_disabled=True,
            force_refresh=True,
        )
        assert d.should_run is False
        assert d.strategy == "skip"


# ─── cache_hit retorna SKIP ───────────────────────────────────────────────────

class TestCacheHit:

    def test_cache_hit_retorna_skip(self) -> None:
        d = resolve_strategy("n1", "sql_database", {}, is_cache_hit=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "cache_hit"

    def test_cache_hit_filter(self) -> None:
        d = resolve_strategy("n1", "filter", {}, is_cache_hit=True)
        assert d.should_run is False
        assert d.strategy == "skip"

    def test_cache_miss_roda(self) -> None:
        d = resolve_strategy("n1", "sql_database", {}, is_cache_hit=False)
        assert d.should_run is True


# ─── cache_miss + node cacheable → estratégia padrão ─────────────────────────

class TestCacheMissDefaultStrategy:

    def test_sql_database_io_thread(self) -> None:
        d = resolve_strategy("n1", "sql_database", {})
        assert d.should_run is True
        assert d.strategy == "io_thread"
        assert d.reason == "io_node"

    def test_join_local_thread_fallback(self) -> None:
        """join é data_worker, mas Fase 5 faz fallback para local_thread."""
        d = resolve_strategy("n1", "join", {})
        assert d.should_run is True
        # DATA_WORKER é a declarada mas _effective_strategy retorna local_thread.
        assert d.strategy == "data_worker"   # resolve_strategy retorna o declarado
        assert d.reason == "wide_heavy"

    def test_lookup_wide_heavy(self) -> None:
        d = resolve_strategy("n1", "lookup", {})
        assert d.should_run is True
        assert d.reason == "wide_heavy"

    def test_aggregator_wide_default(self) -> None:
        """aggregator tem shape=wide, default_strategy=local_thread → wide_default."""
        d = resolve_strategy("n1", "aggregator", {})
        assert d.should_run is True
        assert d.reason == "wide_default"


# ─── nunca rodou → estratégia padrão ─────────────────────────────────────────

class TestNuncaRodou:

    def test_filter_narrow_default(self) -> None:
        d = resolve_strategy("n1", "filter", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"
        assert d.reason == "narrow_default"

    def test_mapper_narrow_default(self) -> None:
        d = resolve_strategy("n1", "mapper", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"

    def test_sort_wide_default(self) -> None:
        d = resolve_strategy("n1", "sort", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"
        assert d.reason == "wide_default"

    def test_tipo_desconhecido_fallback(self) -> None:
        d = resolve_strategy("n1", "tipo_inexistente_xyz", {})
        assert isinstance(d, StrategyDecision)
        assert d.should_run is True  # fallback: narrow_default


# ─── pinned / disabled retorna SKIP ──────────────────────────────────────────

class TestPinnedDisabled:

    def test_pinned_retorna_skip(self) -> None:
        d = resolve_strategy("n1", "filter", {}, is_pinned=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "pinned_output"

    def test_disabled_retorna_skip(self) -> None:
        d = resolve_strategy("n1", "filter", {}, is_disabled=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "disabled"

    def test_checkpoint_retorna_skip(self) -> None:
        d = resolve_strategy("n1", "filter", {}, is_checkpoint=True)
        assert d.should_run is False
        assert d.strategy == "skip"
        assert d.reason == "checkpoint_restored"

    def test_prioridade_disabled_sobre_cache_hit(self) -> None:
        d = resolve_strategy("n1", "filter", {}, is_disabled=True, is_cache_hit=True)
        assert d.reason == "disabled"  # disabled tem prioridade

    def test_prioridade_pinned_sobre_force_refresh(self) -> None:
        d = resolve_strategy("n1", "filter", {}, is_pinned=True, force_refresh=True)
        assert d.should_run is False
        assert d.reason == "pinned_output"


# ─── Shapes e estratégias ─────────────────────────────────────────────────────

class TestShapesAndStrategies:

    def test_control_node_local_thread(self) -> None:
        d = resolve_strategy("n1", "ifElse", {})
        assert d.should_run is True
        assert d.strategy == "local_thread"
        assert d.reason == "control_node"

    def test_io_node_io_thread(self) -> None:
        d = resolve_strategy("n1", "http_request", {})
        assert d.should_run is True
        assert d.strategy == "io_thread"
        assert d.reason == "io_node"

    @pytest.mark.parametrize("node_type,expected_reason", [
        ("filter",      "narrow_default"),
        ("mapper",      "narrow_default"),
        ("math",        "narrow_default"),
        ("sort",        "wide_default"),
        ("pivot",       "wide_default"),
        ("aggregator",  "wide_default"),
        ("join",        "wide_heavy"),
        ("lookup",      "wide_heavy"),
        ("ifElse",      "control_node"),
        ("loadNode",    "output_node"),
        ("sql_database","io_node"),
    ])
    def test_reason_por_tipo(self, node_type: str, expected_reason: str) -> None:
        d = resolve_strategy("n1", node_type, {})
        assert d.reason == expected_reason, (
            f"node_type={node_type!r}: esperado reason={expected_reason!r}, "
            f"obtido={d.reason!r}"
        )


# ─── Timing (< 5ms) ──────────────────────────────────────────────────────────

class TestTiming:

    def test_resolver_timing_menor_5ms(self) -> None:
        import time  # noqa: PLC0415
        t0 = time.monotonic()
        for _ in range(100):
            resolve_strategy("n1", "join", {})
        elapsed_ms = (time.monotonic() - t0) * 1000
        avg_ms = elapsed_ms / 100
        assert avg_ms < 5.0, f"Resolver médio {avg_ms:.3f}ms > 5ms"


# ─── build_strategy_sse_event ─────────────────────────────────────────────────

class TestBuildStrategySseEvent:

    def test_shape_evento(self) -> None:
        d = StrategyDecision(True, "local_thread", "narrow_default")
        evt = build_strategy_sse_event(
            "n1", "filter", "exec-123", d, label="Filtro", semantic_hash="abc123"
        )
        assert evt["type"] == "node_strategy_resolved"
        assert evt["node_id"] == "n1"
        assert evt["node_type"] == "filter"
        assert evt["strategy"] == "local_thread"
        assert evt["should_run"] is True
        assert evt["reason"] == "narrow_default"
        assert evt["label"] == "Filtro"
        assert evt["execution_id"] == "exec-123"
        assert evt["semantic_hash"] == "abc123"

    def test_shape_sem_hash(self) -> None:
        d = StrategyDecision(False, "skip", "cache_hit")
        evt = build_strategy_sse_event("n2", "sql_database", None, d)
        assert evt["semantic_hash"] is None
        assert evt["should_run"] is False
