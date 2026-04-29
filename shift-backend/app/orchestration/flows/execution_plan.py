"""
ExecutionPlanSnapshot — snapshot imutável do plano de execução.

Capturado logo após o topological sort em dynamic_runner.py, antes de
qualquer nó rodar. Persiste em workflow_executions.plan_snapshot (JSONB).

Serve para:
- Auditar qual era o plano antes de falhas.
- Validar heurísticas do StrategyObserver comparando predicted vs real.
- Debug de grafos grandes (quais níveis paralelos foram previstos).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.orchestration.flows.node_profile import get_profile


class PredictedNodeStrategy(BaseModel):
    strategy: str
    shape: str
    reason: str


class ExecutionPlanSnapshot(BaseModel):
    execution_id: UUID
    plan_version: int = 1
    levels: list[list[str]]
    node_count: int
    edge_count: int
    skip_nodes: list[str] = Field(default_factory=list)
    predicted_strategies: dict[str, PredictedNodeStrategy]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat(), UUID: str}}


def _predict_strategy(node_type: str, node_data: dict[str, Any]) -> PredictedNodeStrategy:
    """Prevê estratégia baseada no perfil estático."""
    profile = get_profile(node_type)
    shape = profile["shape"]
    strategy = profile["default_strategy"]

    # Nós de output sempre rodam (nunca podem ser cacheados).
    if shape == "output":
        reason = "output_node"
    elif shape == "control":
        reason = "control_node"
    elif shape == "io":
        reason = "io_node"
    elif strategy == "data_worker":
        reason = "wide_heavy"
    else:
        reason = f"{shape}_default"

    return PredictedNodeStrategy(strategy=strategy, shape=shape, reason=reason)


def build_snapshot(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    levels: list[list[str]],
    execution_id: str | UUID | None,
) -> ExecutionPlanSnapshot:
    """Constrói o snapshot do plano a partir do grafo já computado.

    Deve ser chamado logo após _topological_sort_levels() no dynamic_runner.
    """
    eid = UUID(str(execution_id)) if execution_id else uuid4()

    # Identifica nós desabilitados que serão pulados.
    skip_nodes = [
        str(n["id"])
        for n in nodes
        if isinstance(n.get("data"), dict) and n["data"].get("enabled") is False
    ]

    predicted: dict[str, PredictedNodeStrategy] = {}
    node_map = {str(n["id"]): n for n in nodes}

    for level in levels:
        for node_id in level:
            node = node_map.get(node_id, {})
            node_data = node.get("data", {}) if isinstance(node.get("data"), dict) else {}
            # Resolve tipo com mesma lógica do runner.
            node_type = str(node.get("type") or node_data.get("type", "unknown"))
            if node_type == "triggerNode":
                trigger_type = str(node_data.get("trigger_type", "manual"))
                node_type = "cron" if trigger_type == "schedule" else trigger_type
            predicted[node_id] = _predict_strategy(node_type, node_data)

    return ExecutionPlanSnapshot(
        execution_id=eid,
        levels=levels,
        node_count=len(nodes),
        edge_count=len(edges),
        skip_nodes=skip_nodes,
        predicted_strategies=predicted,
    )
