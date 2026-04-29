"""
StrategyObserver — modo passivo (Fase 4).

Calcula qual estratégia SERIA aplicada em cada nó e loga/emite SSE, mas
NÃO muda o comportamento do runner. Os dados coletados validam heurísticas
antes da Fase 5 ativar o resolver real.

Baseado no _decide_execution() do Flowfile (flowfile-mechanisms.md §1),
adaptado para os enums do Shift:
  - SKIP          : nó não deve rodar (output_node nunca skip; cache hit)
  - local_thread  : asyncio.to_thread com processor síncrono (padrão atual)
  - data_worker   : subprocess isolado (Fase 6 — previsto, não ativo ainda)
  - io_thread     : asyncio.to_thread com I/O externo (semântica futura)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.orchestration.flows.node_profile import get_profile

logger = logging.getLogger(__name__)


@dataclass
class StrategyDecision:
    should_run: bool
    strategy: str   # "skip" | "local_thread" | "data_worker" | "io_thread"
    reason: str     # legível por humanos e pesquisável em SQL/Grafana


def observe_strategy(
    node_id: str,
    node_type: str,
    node_data: dict[str, Any],
    run_mode: str = "full",
    is_pinned: bool = False,
    is_disabled: bool = False,
    is_checkpoint: bool = False,
    is_cache_hit: bool = False,
) -> StrategyDecision:
    """Calcula e loga a estratégia prevista para um nó.

    Modo passivo: o retorno é informativo. O runner continua com seu
    comportamento atual independente do resultado desta função.

    Mirrors flowfile's _decide_execution order of precedence:
    1. disabled / pinned / checkpoint → skip
    2. cache hit → skip
    3. output_node → sempre roda
    4. shape do perfil → estratégia padrão
    """
    profile = get_profile(node_type)
    shape = profile["shape"]
    default_strategy = profile["default_strategy"]

    # 1. Shortcuts que nunca chegam ao processor.
    if is_disabled:
        decision = StrategyDecision(False, "skip", "disabled")
    elif is_pinned:
        decision = StrategyDecision(False, "skip", "pinned_output")
    elif is_checkpoint:
        decision = StrategyDecision(False, "skip", "checkpoint_restored")
    elif is_cache_hit:
        decision = StrategyDecision(False, "skip", "cache_hit")

    # 2. Output nodes always run.
    elif shape == "output":
        decision = StrategyDecision(True, default_strategy, "output_node")

    # 3. Regra de estratégia por shape.
    elif shape == "control":
        decision = StrategyDecision(True, "local_thread", "control_node")
    elif shape == "io":
        decision = StrategyDecision(True, "io_thread", "io_node")
    elif default_strategy == "data_worker":
        decision = StrategyDecision(True, "data_worker", "wide_heavy")
    else:
        decision = StrategyDecision(True, default_strategy, f"{shape}_default")

    # Log estruturado — pronto para análise em SQL/Grafana.
    logger.debug(
        "strategy_observed",
        extra={
            "node_id": node_id,
            "node_type": node_type,
            "shape": shape,
            "strategy": decision.strategy,
            "reason": decision.reason,
            "should_run": decision.should_run,
            "run_mode": run_mode,
        },
    )

    return decision


def build_strategy_sse_event(
    node_id: str,
    node_type: str,
    execution_id: str | None,
    decision: StrategyDecision,
    label: str | None = None,
) -> dict[str, Any]:
    """Monta o payload SSE para node_strategy_observed."""
    return {
        "type": "node_strategy_observed",
        "execution_id": execution_id,
        "node_id": node_id,
        "node_type": node_type,
        "label": label,
        "strategy": decision.strategy,
        "should_run": decision.should_run,
        "reason": decision.reason,
    }
