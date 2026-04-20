"""
No final — gera a resposta em linguagem natural ao usuario.

Pode consumir: guardrails_violation (curto-circuito), error (aborto),
executed_actions (resumos em preview) ou current_intent (chat simples).
Sempre retorna final_report e marca a thread como completed/failed.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.graph.llm import llm_complete_with_usage
from app.services.agent.graph.prompts import REPORT_PROMPT
from app.services.agent.graph.state import PlatformAgentState
from app.services.agent.persistence import update_thread_status

logger = get_logger(__name__)


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


async def _set_status(thread_id: str | None, status: str) -> None:
    if not thread_id:
        return
    try:
        async with async_session_factory() as session:
            await update_thread_status(
                session, thread_id=UUID(thread_id), status=status
            )
    except Exception:  # noqa: BLE001
        logger.exception("agent.report.status_update_failed", thread_id=thread_id)


async def report_node(state: PlatformAgentState) -> dict[str, Any]:
    """Produz o final_report e atualiza o status da thread."""
    thread_id = state.get("thread_id")
    violation = state.get("guardrails_violation")
    error = state.get("error")
    executed = state.get("executed_actions") or []
    intent = state.get("current_intent") or {}
    user_text = _last_user_message(state.get("messages", []))
    soft_cap = state.get("token_soft_cap_reason")

    if soft_cap:
        report = soft_cap
        await _set_status(thread_id, "completed")
        return {
            "final_report": report,
            "messages": [{"role": "assistant", "content": report}],
        }

    clarification = state.get("clarification_question")
    if clarification and not executed:
        await _set_status(thread_id, "completed")
        return {
            "final_report": clarification,
            "messages": [{"role": "assistant", "content": clarification}],
        }

    if violation:
        report = (
            "Nao posso atender a este pedido: "
            f"{violation}\n\nReformule a solicitacao dentro do escopo da plataforma."
        )
        await _set_status(thread_id, "completed")
        return {
            "final_report": report,
            "messages": [{"role": "assistant", "content": report}],
        }

    if error and not executed:
        report = f"Operacao interrompida: {error}"
        await _set_status(thread_id, "failed")
        return {
            "final_report": report,
            "messages": [{"role": "assistant", "content": report}],
        }

    payload = {
        "intent": intent,
        "user_message": user_text[:4000],
        "executed_actions": [
            {
                "tool": a.get("tool"),
                "arguments": a.get("arguments"),
                "status": a.get("status"),
                "preview": a.get("preview"),
                "error": a.get("error"),
            }
            for a in executed
        ],
        "error": error,
    }

    usage_entry: dict[str, Any] | None = None
    try:
        response = await llm_complete_with_usage(
            system=REPORT_PROMPT,
            user=json.dumps(payload, ensure_ascii=False),
        )
        report = response.content
        usage_entry = {**response.usage_entry(), "node": "report"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent.report.llm_failed", thread_id=thread_id)
        report = (
            "Tive um problema ao redigir a resposta final, mas as acoes "
            f"foram registradas. Detalhe: {exc}"
        )

    await _set_status(thread_id, "completed" if not error else "failed")

    result: dict[str, Any] = {
        "final_report": report,
        "messages": [{"role": "assistant", "content": report}],
    }
    if usage_entry is not None:
        result["token_usage"] = [usage_entry]
    return result
