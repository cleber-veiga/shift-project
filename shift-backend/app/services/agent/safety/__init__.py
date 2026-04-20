"""
Modulo de seguranca do Platform Agent (Fase 6).

Expoe sanitizer anti-prompt-injection, servico de orcamentos (budgets)
por usuario/workspace, e job periodico de expiracao de aprovacoes.
"""

from __future__ import annotations

from app.services.agent.safety.budget_config import (
    AgentBudget,
    DEFAULT_BUDGET,
    get_budget_for_workspace,
)
from app.services.agent.safety.budget_service import (
    BudgetCheckResult,
    TokenBudgetResult,
    agent_budget_service,
)
from app.services.agent.safety.sanitizer import (
    sanitize_tool_result,
    wrap_tool_result,
)

__all__ = [
    "AgentBudget",
    "DEFAULT_BUDGET",
    "get_budget_for_workspace",
    "BudgetCheckResult",
    "TokenBudgetResult",
    "agent_budget_service",
    "sanitize_tool_result",
    "wrap_tool_result",
]
