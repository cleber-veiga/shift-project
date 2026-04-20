"""
No de aprovacao humana.

Se houver alguma proposed_action com requires_approval, persiste um registro
em agent_approvals e suspende o grafo via interrupt(). O resume traz a decisao
({'approved': bool, 'decided_by': str, 'rejection_reason': str|None}).

Se nenhuma acao exige aprovacao, passa direto as proposed_actions como
approved_actions.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langgraph.types import interrupt

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.graph.state import PlatformAgentState
from app.services.agent.persistence import (
    create_approval,
    mark_approval_decision,
    update_thread_status,
)

logger = get_logger(__name__)


def _to_frontend_plan(
    intent_data: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    current_intent = intent_data or {}
    planned_actions = actions or []
    summary = str(current_intent.get("summary") or "").strip()
    intent = str(current_intent.get("intent") or "acao")

    steps = [
        {
            "step": index + 1,
            "description": action.get("rationale")
            or f"Executar {action.get('tool') or 'acao'}",
            "tool_calls": [
                {
                    "tool_name": action.get("tool"),
                    "arguments": action.get("arguments") or {},
                    "rationale": action.get("rationale") or "",
                    "requires_approval": bool(action.get("requires_approval")),
                }
            ],
        }
        for index, action in enumerate(planned_actions)
        if isinstance(action, dict)
    ]

    impact = []
    if any(
        action.get("requires_approval")
        for action in planned_actions
        if isinstance(action, dict)
    ):
        impact.append("Pode exigir aprovacao antes de executar.")
    if planned_actions:
        impact.append(f"{len(planned_actions)} acao(oes) planejada(s).")

    return {
        "intent": intent,
        "summary": summary or "Plano de acao sugerido pelo agente.",
        "impact": " ".join(impact),
        "steps": steps,
    }


async def human_approval_node(state: PlatformAgentState) -> dict[str, Any]:
    """Cria solicitacao de aprovacao se necessario e pausa o grafo."""
    proposed = state.get("proposed_actions") or []

    needs_approval = [a for a in proposed if a.get("requires_approval")]
    if not needs_approval:
        return {
            "approved_actions": proposed,
            "approval_id": None,
        }

    thread_id_str = state.get("thread_id")
    if not thread_id_str:
        return {
            "approved_actions": [],
            "approval_id": None,
            "error": "thread_id ausente em human_approval_node",
        }
    thread_uuid = UUID(thread_id_str)

    plan_payload = _to_frontend_plan(state.get("current_intent"), proposed)

    async with async_session_factory() as session:
        approval_id = await create_approval(
            session,
            thread_id=thread_uuid,
            proposed_plan=plan_payload,
        )
        await update_thread_status(
            session,
            thread_id=thread_uuid,
            status="awaiting_approval",
        )

    logger.info(
        "agent.approval.pending",
        thread_id=thread_id_str,
        approval_id=str(approval_id),
        actions=len(proposed),
    )

    decision = interrupt(
        {
            "type": "approval_required",
            "approval_id": str(approval_id),
            "plan": plan_payload,
        }
    )

    approved = bool(decision.get("approved", False)) if isinstance(decision, dict) else False
    decided_by_raw = decision.get("decided_by") if isinstance(decision, dict) else None
    rejection_reason = (
        decision.get("rejection_reason") if isinstance(decision, dict) else None
    )

    if decided_by_raw is None:
        ctx = state.get("user_context") or {}
        decided_by_raw = ctx.get("user_id")

    try:
        decided_by_uuid = UUID(str(decided_by_raw)) if decided_by_raw else None
    except (TypeError, ValueError):
        decided_by_uuid = None

    async with async_session_factory() as session:
        if decided_by_uuid is not None:
            await mark_approval_decision(
                session,
                approval_id=approval_id,
                approved=approved,
                decided_by=decided_by_uuid,
                rejection_reason=rejection_reason,
            )
        await update_thread_status(
            session,
            thread_id=thread_uuid,
            status="running" if approved else "completed",
        )

    logger.info(
        "agent.approval.resolved",
        thread_id=thread_id_str,
        approval_id=str(approval_id),
        approved=approved,
    )

    if not approved:
        return {
            "approved_actions": [],
            "approval_id": str(approval_id),
            "error": rejection_reason or "Acoes rejeitadas pelo usuario.",
        }

    return {
        "approved_actions": proposed,
        "approval_id": str(approval_id),
    }
