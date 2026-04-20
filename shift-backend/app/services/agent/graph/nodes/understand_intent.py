"""
No de classificacao de intencao.

Determina se a mensagem e query/action/diagnose/chat. O resultado e
usado pelo planner e influencia o roteamento apos planejamento.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.agent.base import sanitize_llm_string
from app.services.agent.graph.llm import llm_complete_json_with_usage
from app.services.agent.graph.prompts import INTENT_PROMPT
from app.services.agent.graph.state import PlatformAgentState

logger = get_logger(__name__)

_VALID = {"query", "action", "diagnose", "chat"}


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


async def understand_intent_node(state: PlatformAgentState) -> dict[str, Any]:
    """Classifica a intencao do usuario e devolve em current_intent."""
    user_text = sanitize_llm_string(_last_user_message(state.get("messages", [])))
    result, usage = await llm_complete_json_with_usage(
        system=INTENT_PROMPT,
        user=user_text[:4000],
        fallback={"intent": "chat", "summary": ""},
    )
    usage_entry = {**usage.usage_entry(), "node": "understand_intent"}

    intent = str(result.get("intent", "chat")).lower()
    if intent not in _VALID:
        intent = "chat"
    summary = str(result.get("summary") or "")[:280]

    logger.info(
        "agent.intent.classified",
        thread_id=state.get("thread_id"),
        intent=intent,
    )
    return {
        "current_intent": {"intent": intent, "summary": summary},
        "token_usage": [usage_entry],
    }
