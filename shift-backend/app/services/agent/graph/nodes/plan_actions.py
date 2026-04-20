"""
No planejador — monta a lista de tool calls a serem executadas.

Recebe a intencao e o catalogo de tools (apenas schemas, nunca a funcao)
e devolve proposed_actions. Se nenhuma tool for necessaria, retorna lista
vazia e o grafo pula direto para report.

Fase 6: verifica soft cap de tokens antes de chamar o LLM; quando a
thread excede o limite, curto-circuita setando token_soft_cap_reason
para que report_node produza a mensagem amigavel.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.base import sanitize_llm_string
from app.services.agent.graph.llm import llm_complete_json_with_usage
from app.services.agent.graph.prompts import PLANNER_PROMPT
from app.services.agent.graph.state import PlatformAgentState
from app.services.agent.safety.budget_service import agent_budget_service
from app.services.agent.tools.registry import TOOL_REGISTRY, TOOL_SCHEMAS

logger = get_logger(__name__)


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _uuid_or_none(raw: Any) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


async def _check_soft_cap(state: PlatformAgentState) -> str | None:
    """Retorna o motivo do soft cap, se atingido; senao None."""
    ctx = state.get("user_context") or {}
    user_id = _uuid_or_none(ctx.get("user_id"))
    workspace_id = _uuid_or_none(ctx.get("workspace_id"))
    thread_id = _uuid_or_none(state.get("thread_id"))
    if user_id is None or workspace_id is None:
        return None
    try:
        async with async_session_factory() as session:
            result = await agent_budget_service.check_token_budget(
                session,
                user_id=user_id,
                thread_id=thread_id,
                workspace_id=workspace_id,
            )
        if result.reason:
            return result.reason
    except Exception:  # noqa: BLE001
        logger.exception(
            "agent.planner.token_budget_check_failed",
            thread_id=state.get("thread_id"),
        )
    return None


async def plan_actions_node(state: PlatformAgentState) -> dict[str, Any]:
    """Produz proposed_actions a partir da mensagem e da intencao."""
    soft_cap_reason = await _check_soft_cap(state)
    if soft_cap_reason:
        logger.info(
            "agent.planner.soft_cap_hit",
            thread_id=state.get("thread_id"),
        )
        return {
            "proposed_actions": [],
            "token_soft_cap_reason": soft_cap_reason,
        }

    user_text = sanitize_llm_string(_last_user_message(state.get("messages", [])))
    intent = state.get("current_intent") or {"intent": "chat", "summary": ""}
    catalog = [
        {
            "name": s["function"]["name"],
            "description": s["function"]["description"],
            "parameters": s["function"]["parameters"],
        }
        for s in TOOL_SCHEMAS
    ]

    user_payload = json.dumps(
        {
            "intent": intent,
            "user_message": user_text[:4000],
            "available_tools": catalog,
        },
        ensure_ascii=False,
    )

    result, usage = await llm_complete_json_with_usage(
        system=PLANNER_PROMPT,
        user=user_payload,
        fallback={"actions": []},
    )
    usage_entry = {**usage.usage_entry(), "node": "plan_actions"}

    clarification = result.get("clarification_question")
    if isinstance(clarification, str) and clarification.strip():
        question = sanitize_llm_string(clarification.strip())[:500]
        logger.info(
            "agent.planner.clarification_needed",
            thread_id=state.get("thread_id"),
        )
        return {
            "proposed_actions": [],
            "clarification_question": question,
            "token_usage": [usage_entry],
        }

    raw_actions = result.get("actions") or []
    if not isinstance(raw_actions, list):
        raw_actions = []

    planned: list[dict[str, Any]] = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or tool not in TOOL_REGISTRY:
            logger.warning(
                "agent.planner.unknown_tool",
                tool=tool,
                thread_id=state.get("thread_id"),
            )
            continue
        args = item.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        rationale = str(item.get("rationale") or "")[:280]
        planned.append(
            {
                "tool": tool,
                "arguments": args,
                "rationale": rationale,
                "requires_approval": TOOL_REGISTRY[tool]["requires_approval"],
            }
        )

    logger.info(
        "agent.planner.planned",
        thread_id=state.get("thread_id"),
        count=len(planned),
    )
    return {"proposed_actions": planned, "token_usage": [usage_entry]}
