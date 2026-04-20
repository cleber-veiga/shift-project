"""
Configuracao de orcamentos (budgets) do Platform Agent.

Define limites default (mensagens/hora, destructive execs, tokens) e
permite overrides por workspace via settings.AGENT_BUDGET_OVERRIDES_JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentBudget:
    """Limites de consumo aplicados por workspace."""

    messages_per_hour: int
    messages_per_day: int
    destructive_executions_per_hour: int
    destructive_executions_per_day: int
    tokens_per_thread: int
    tokens_per_user_per_day: int


DEFAULT_BUDGET = AgentBudget(
    messages_per_hour=60,
    messages_per_day=500,
    destructive_executions_per_hour=10,
    destructive_executions_per_day=50,
    tokens_per_thread=100_000,
    tokens_per_user_per_day=2_000_000,
)


_ALLOWED_FIELDS = {
    "messages_per_hour",
    "messages_per_day",
    "destructive_executions_per_hour",
    "destructive_executions_per_day",
    "tokens_per_thread",
    "tokens_per_user_per_day",
}


def _parse_overrides() -> dict[str, dict[str, int]]:
    raw = (getattr(settings, "AGENT_BUDGET_OVERRIDES_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {}
        result: dict[str, dict[str, int]] = {}
        for key, value in parsed.items():
            if not isinstance(value, dict):
                continue
            filtered: dict[str, int] = {}
            for field, v in value.items():
                if field in _ALLOWED_FIELDS and isinstance(v, int) and v >= 0:
                    filtered[field] = v
            if filtered:
                result[str(key)] = filtered
        return result
    except (json.JSONDecodeError, ValueError):
        logger.warning("agent.budget.overrides_parse_failed")
        return {}


_OVERRIDES: dict[str, dict[str, int]] | None = None


def _get_overrides() -> dict[str, dict[str, int]]:
    global _OVERRIDES
    if _OVERRIDES is None:
        _OVERRIDES = _parse_overrides()
    return _OVERRIDES


def reset_overrides_cache() -> None:
    """Util para testes: reloads overrides do settings."""
    global _OVERRIDES
    _OVERRIDES = None


def get_budget_for_workspace(workspace_id: UUID | str) -> AgentBudget:
    """Retorna o orcamento aplicavel ao workspace (default + overrides)."""
    overrides = _get_overrides().get(str(workspace_id))
    if not overrides:
        return DEFAULT_BUDGET
    kwargs: dict[str, Any] = dict(overrides)
    return replace(DEFAULT_BUDGET, **kwargs)
