"""Testes de resolucao de budgets por workspace, incluindo overrides."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from app.services.agent.safety.budget_config import (
    DEFAULT_BUDGET,
    get_budget_for_workspace,
    reset_overrides_cache,
)


def test_default_budget_when_no_override():
    reset_overrides_cache()
    ws_id = uuid4()
    with patch(
        "app.services.agent.safety.budget_config.settings.AGENT_BUDGET_OVERRIDES_JSON",
        "",
    ):
        reset_overrides_cache()
        budget = get_budget_for_workspace(ws_id)
    assert budget == DEFAULT_BUDGET


def test_partial_override_merges_with_defaults():
    ws_id = uuid4()
    overrides_json = (
        f'{{"{ws_id}": {{"messages_per_hour": 5, "tokens_per_thread": 42}}}}'
    )
    with patch(
        "app.services.agent.safety.budget_config.settings.AGENT_BUDGET_OVERRIDES_JSON",
        overrides_json,
    ):
        reset_overrides_cache()
        budget = get_budget_for_workspace(ws_id)
    assert budget.messages_per_hour == 5
    assert budget.tokens_per_thread == 42
    assert budget.messages_per_day == DEFAULT_BUDGET.messages_per_day
    assert (
        budget.destructive_executions_per_hour
        == DEFAULT_BUDGET.destructive_executions_per_hour
    )


def test_override_only_applies_to_target_workspace():
    ws_a = uuid4()
    ws_b = uuid4()
    overrides_json = f'{{"{ws_a}": {{"messages_per_hour": 1}}}}'
    with patch(
        "app.services.agent.safety.budget_config.settings.AGENT_BUDGET_OVERRIDES_JSON",
        overrides_json,
    ):
        reset_overrides_cache()
        budget_a = get_budget_for_workspace(ws_a)
        budget_b = get_budget_for_workspace(ws_b)
    assert budget_a.messages_per_hour == 1
    assert budget_b == DEFAULT_BUDGET


def test_malformed_overrides_fall_back_to_default():
    ws_id = uuid4()
    with patch(
        "app.services.agent.safety.budget_config.settings.AGENT_BUDGET_OVERRIDES_JSON",
        "not-valid-json{",
    ):
        reset_overrides_cache()
        budget = get_budget_for_workspace(ws_id)
    assert budget == DEFAULT_BUDGET
