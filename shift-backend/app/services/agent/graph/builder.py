"""
Constroi o StateGraph do Platform Agent.

Fluxo:
  START -> guardrails
    - violou? -> report (curto-circuito)
    - ok       -> understand_intent
  understand_intent -> load_workflow_context
  load_workflow_context -> plan_actions
  plan_actions
    - intencao de build -> build_workflow
    - sem acoes         -> report
    - com acoes         -> human_approval
  human_approval
    - interrompe se alguma acao exige aprovacao
    - rejeitadas -> report
    - aprovadas  -> execute
  execute -> report
  build_workflow -> report  (apos interrupt() + confirm/cancel)
  report -> END
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.services.agent.graph.nodes import (
    build_workflow_node,
    execute_node,
    guardrails_node,
    human_approval_node,
    load_workflow_context_node,
    plan_actions_node,
    report_node,
    understand_intent_node,
)
from app.services.agent.graph.state import PlatformAgentState


def _after_guardrails(state: PlatformAgentState) -> str:
    return "report" if state.get("guardrails_violation") else "understand_intent"


def _after_plan(state: PlatformAgentState) -> str:
    if (state.get("build_plan") or {}).get("workflow_id"):
        return "build_workflow"
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
    graph.add_node("load_workflow_context", load_workflow_context_node)
    graph.add_node("plan_actions", plan_actions_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("execute", execute_node)
    graph.add_node("report", report_node)
    graph.add_node("build_workflow", build_workflow_node)

    graph.add_edge(START, "guardrails")
    graph.add_conditional_edges(
        "guardrails",
        _after_guardrails,
        {"report": "report", "understand_intent": "understand_intent"},
    )
    graph.add_edge("understand_intent", "load_workflow_context")
    graph.add_edge("load_workflow_context", "plan_actions")
    graph.add_conditional_edges(
        "plan_actions",
        _after_plan,
        {"human_approval": "human_approval", "build_workflow": "build_workflow", "report": "report"},
    )
    graph.add_conditional_edges(
        "human_approval",
        _after_approval,
        {"execute": "execute", "report": "report"},
    )
    graph.add_edge("execute", "report")
    graph.add_edge("build_workflow", "report")
    graph.add_edge("report", END)

    return graph.compile(checkpointer=checkpointer)
