"""
Estado do grafo LangGraph do Platform Agent.

Todo no recebe e retorna um dicionario derivado deste TypedDict.
O historico (messages) e actions acumulado via reducer add; os demais
campos sao sobrescritos pela propria retorno do no (merge raso).
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


class PlatformAgentState(TypedDict, total=False):
    """Estado mutavel de uma execucao do grafo do Platform Agent.

    Campos:
      thread_id: identificador da thread; casa com agent_threads.id
                  e com o checkpoint do LangGraph.
      user_context: UserContext serializado para dict (frozen dataclass
                    nao entra direto no checkpointer JSONB).
      messages: historico OpenAI-style (role/content/tool_calls/tool_call_id).
                Reducer 'add' permite que nos retornem apenas o que adicionar.
      current_intent: classificacao produzida por understand_intent_node.
      proposed_actions: lista de tool calls planejada pelo planner.
      approved_actions: tool calls aprovadas apos human_approval_node.
      approval_id: UUID do registro em agent_approvals (string).
      executed_actions: resultado de cada tool call executada pelo executor.
      final_report: resposta em linguagem natural ao usuario.
      error: mensagem de erro quando um no decide abortar a thread.
      guardrails_violation: motivo de veto quando guardrails_node bloqueia.
    """

    thread_id: str
    user_context: dict[str, Any]
    messages: Annotated[list[dict[str, Any]], add]
    current_intent: dict[str, Any]
    proposed_actions: list[dict[str, Any]]
    approved_actions: list[dict[str, Any]]
    approval_id: str | None
    executed_actions: Annotated[list[dict[str, Any]], add]
    final_report: str
    error: str | None
    guardrails_violation: str | None
    # Fase 6: entradas de uso de LLM acumuladas durante o turno,
    # consumidas por chat_service para persistir em msg_metadata.
    token_usage: Annotated[list[dict[str, Any]], add]
    # Fase 6: aviso soft-cap de tokens por thread (mostrado no report).
    token_soft_cap_reason: str | None
    # Pergunta de clarificacao ao usuario quando o planner detecta
    # parametros obrigatorios ausentes que so o usuario pode fornecer
    # (ex: nome de um novo projeto). Curto-circuita para report_node.
    clarification_question: str | None
    # Payload estruturado que acompanha clarification_question quando
    # o planner quer oferecer opcoes selecionaveis (chips/radio no chat)
    # em vez de texto livre. Shape:
    #   {
    #     "kind": "choice" | "multi_choice",
    #     "field": "connection_id" | "trigger_type" | ...,
    #     "question": "...",  # espelha clarification_question
    #     "options": [
    #       {"value": "<id>", "label": "Nome", "hint": "metadado extra"}
    #     ],
    #     "extra_option": {"value": "...", "label": "...", "hint": "..."}
    #   }
    clarification: dict[str, Any] | None
    # Fase 4: build mode — ID da build session ativa (string UUID).
    build_session_id: str | None
    # Fase 4: plano estruturado de mutacoes produzido pelo build planner.
    # Campos: workflow_id, ops: [{op, node_type, label, config, ...}], summary.
    build_plan: dict[str, Any] | None
    # Fase 4: contexto do workflow alvo (nos/arestas existentes) para o planner.
    workflow_context: dict[str, Any] | None
