"""
StrategyResolver — decisor ativo de estratégia de execução (Fase 5).

Promove o StrategyObserver da Fase 4 a decisor real. O dynamic_runner.py
CONSULTA a decisão e a respeita:

  - SKIP        : nó pulado; marcar como skipped; ainda emitir eventos SSE.
  - LOCAL_THREAD : comportamento atual (asyncio.to_thread com processor síncrono).
  - DATA_WORKER  : TODO Fase 6 — por ora fallback para LOCAL_THREAD com log.
  - IO_THREAD    : idem LOCAL_THREAD por enquanto; semântica futura de pool separado.

Ordem de prioridade (mirrors Flowfile _decide_execution §1):
  1. disabled / pinned / checkpoint  → skip (incondicionais)
  2. force_refresh                   → sempre roda, ignora cache
  3. cache_hit                       → skip
  4. output_node                     → sempre roda
  5. shape do perfil                 → estratégia padrão

Hot path: deve adicionar < 5 ms por nó. Apenas lookups em dict + condicionais.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.orchestration.flows.node_profile import get_profile

logger = logging.getLogger(__name__)


@dataclass
class StrategyDecision:
    should_run: bool
    strategy: str   # "skip" | "local_thread" | "data_worker" | "io_thread"
    reason: str     # legível por humanos e pesquisável em SQL/Grafana


def resolve_strategy(
    node_id: str,
    node_type: str,
    node_data: dict[str, Any],
    run_mode: str = "full",
    is_pinned: bool = False,
    is_disabled: bool = False,
    is_checkpoint: bool = False,
    is_cache_hit: bool = False,
    force_refresh: bool = False,
) -> StrategyDecision:
    """Decide se e como um nó deve executar.

    Retorna ``StrategyDecision`` que o runner DEVE respeitar:
      - ``should_run=False`` → pular nó (ainda emitir SSE de status).
      - ``should_run=True``  → executar com ``strategy`` indicada.

    Timing garantido < 5 ms (só lookups + condicionais, sem I/O).
    """
    _t0 = time.monotonic()

    profile = get_profile(node_type)
    shape = profile["shape"]
    default_strategy = profile["default_strategy"]

    # ── Prioridade 1: shortcuts incondicionais ──────────────────────────────
    if is_disabled:
        decision = StrategyDecision(False, "skip", "disabled")

    elif is_pinned:
        decision = StrategyDecision(False, "skip", "pinned_output")

    elif is_checkpoint:
        decision = StrategyDecision(False, "skip", "checkpoint_restored")

    # ── Prioridade 2: output nodes always run (mirrors Flowfile §1) ─────────
    # Output nodes são verificados ANTES do cache — Flowfile verifica output
    # antes de cache_results, garantindo que outputs sempre materializam.
    elif shape == "output":
        strategy = _effective_strategy(default_strategy)
        decision = StrategyDecision(True, strategy, "output_node")

    # ── Prioridade 3: force_refresh invalida qualquer cache ─────────────────
    elif force_refresh:
        strategy = _effective_strategy(default_strategy)
        decision = StrategyDecision(True, strategy, "force_refresh")

    # ── Prioridade 4: cache hit → skip ──────────────────────────────────────
    elif is_cache_hit:
        decision = StrategyDecision(False, "skip", "cache_hit")

    # ── Prioridade 5: estratégia por shape ──────────────────────────────────
    elif shape == "control":
        decision = StrategyDecision(True, "local_thread", "control_node")

    elif shape == "io":
        decision = StrategyDecision(True, "io_thread", "io_node")

    elif default_strategy == "data_worker":
        # DATA_WORKER é a estratégia declarada — respeitar no evento SSE,
        # mas runner fará fallback para local_thread até Fase 6.
        decision = StrategyDecision(True, "data_worker", "wide_heavy")

    else:
        decision = StrategyDecision(
            True, _effective_strategy(default_strategy), f"{shape}_default"
        )

    elapsed_ms = (time.monotonic() - _t0) * 1_000

    logger.debug(
        "strategy_resolved",
        extra={
            "node_id": node_id,
            "node_type": node_type,
            "shape": shape,
            "strategy": decision.strategy,
            "reason": decision.reason,
            "should_run": decision.should_run,
            "run_mode": run_mode,
            "elapsed_ms": round(elapsed_ms, 3),
        },
    )

    return decision


def _effective_strategy(declared: str) -> str:
    """DATA_WORKER é fallback para LOCAL_THREAD até Fase 6 estar ativa."""
    if declared == "data_worker":
        # TODO(Fase 6): dispatch para DataWorkerRuntime subprocess
        return "local_thread"
    return declared


def build_strategy_sse_event(
    node_id: str,
    node_type: str,
    execution_id: str | None,
    decision: StrategyDecision,
    *,
    label: str | None = None,
    semantic_hash: str | None = None,
    elapsed_ms: float | None = None,
) -> dict[str, Any]:
    """Monta o payload SSE para node_strategy_resolved."""
    return {
        "type": "node_strategy_resolved",
        "execution_id": execution_id,
        "node_id": node_id,
        "node_type": node_type,
        "label": label,
        "strategy": decision.strategy,
        "should_run": decision.should_run,
        "reason": decision.reason,
        "semantic_hash": semantic_hash,
        "elapsed_ms": elapsed_ms,
    }
