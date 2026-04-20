"""
No de guardrails — primeira linha de defesa do Platform Agent.

Classifica a ultima mensagem do usuario para detectar prompt injection,
tentativas de bypass e conteudo fora de escopo. Se violar, curto-circuita
o grafo setando guardrails_violation; o builder roteia direto para report.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.core.logging import get_logger
from app.services.agent.base import sanitize_llm_string
from app.services.agent.graph.llm import llm_complete_json_with_usage
from app.services.agent.graph.prompts import GUARDRAILS_PROMPT
from app.services.agent.graph.state import PlatformAgentState

logger = get_logger(__name__)

_SUSPICIOUS_PATTERNS = (
    r"\bprompt\b",
    r"\binstru[cç][aã]o(?:es)?\b",
    r"\bsystem\b",
    r"\bsistema\b",
    r"\bignore\b",
    r"\bbypass\b",
)


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _is_capabilities_question(text: str) -> bool:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized.strip().lower())
    if not normalized:
        return False
    if any(re.search(pattern, normalized) for pattern in _SUSPICIOUS_PATTERNS):
        return False
    keyword_sets = (
        ("o que", "pode fazer"),
        ("como", "pode ajudar"),
        ("no que", "pode ajudar"),
        ("quais", "funcionalidades"),
        ("quais", "capacidades"),
        ("poderia perguntar",),
        ("posso perguntar",),
        ("como funciona",),
    )
    return any(all(keyword in normalized for keyword in keywords) for keywords in keyword_sets)


async def guardrails_node(state: PlatformAgentState) -> dict[str, Any]:
    """Aplica guardrails sobre a ultima mensagem do usuario."""
    user_text = _last_user_message(state.get("messages", []))
    if not user_text:
        return {"guardrails_violation": None}

    # Perguntas genéricas de ajuda/capacidades do agente são válidas e
    # estavam gerando falso positivo no classificador LLM.
    if _is_capabilities_question(user_text):
        return {"guardrails_violation": None}

    sanitized = sanitize_llm_string(user_text)
    result, usage = await llm_complete_json_with_usage(
        system=GUARDRAILS_PROMPT,
        user=sanitized[:4000],
        fallback={"ok": True, "reason": None},
    )
    usage_entry = {**usage.usage_entry(), "node": "guardrails"}

    ok = bool(result.get("ok", True))
    if ok:
        return {"guardrails_violation": None, "token_usage": [usage_entry]}

    reason = str(result.get("reason") or "mensagem bloqueada por guardrails").strip()
    logger.warning(
        "agent.guardrails.blocked",
        thread_id=state.get("thread_id"),
        reason_preview=reason[:200],
    )
    return {"guardrails_violation": reason, "token_usage": [usage_entry]}
