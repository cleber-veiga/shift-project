"""
Constroi o StateGraph do Platform Agent.

Fluxo:
  START -> guardrails
    - violou? -> report (curto-circuito)
    - ok       -> understand_intent
  understand_intent -> plan_actions
  plan_actions
    - sem acoes -> report
    - com acoes -> human_approval
  human_approval
    - interrompe se alguma acao exige aprovacao
    - rejeitadas -> report
    - aprovadas  -> execute
  execute -> report
  report -> END
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.services.agent.graph.nodes import (
    execute_node,
    guardrails_node,
    human_approval_node,
    plan_actions_node,
    report_node,
    understand_intent_node,
)
from app.services.agent.graph.state import PlatformAgentState


def _after_guardrails(state: PlatformAgentState) -> str:
    return "report" if state.get("guardrails_violation") else "understand_intent"


def _after_plan(state: PlatformAgentState) -> str:
    actions = state.get("proposed_actions") or []
    return "human_approval" if actions else "report"


def _after_approval(state: PlatformAgentState) -> str:
    approved = state.get("approved_actions") or []
    return "execute" if approved else "report"


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Constroi e compila o grafo; checkpointer e opcional para testes unitarios."""
    graph = StateGraph(PlatformAgentState)

    graph.add_node("guardrails", guardrails_node)
    graph.add_node("understand_intent", understand_intent_node)
    graph.add_node("plan_actions", plan_actions_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("execute", execute_node)
    graph.add_node("report", report_node)

    graph.add_edge(START, "guardrails")
    graph.add_conditional_edges(
        "guardrails",
        _after_guardrails,
        {"report": "report", "understand_intent": "understand_intent"},
    )
    graph.add_edge("understand_intent", "plan_actions")
    graph.add_conditional_edges(
        "plan_actions",
        _after_plan,
        {"human_approval": "human_approval", "report": "report"},
    )
    graph.add_conditional_edges(
        "human_approval",
        _after_approval,
        {"execute": "execute", "report": "report"},
    )
    graph.add_edge("execute", "report")
    graph.add_edge("report", END)

    return graph.compile(checkpointer=checkpointer)
