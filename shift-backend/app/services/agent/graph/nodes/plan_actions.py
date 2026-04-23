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
from app.services.agent.graph.prompts import BUILD_PLANNER_PROMPT, PLANNER_PROMPT
from app.services.agent.graph.state import PlatformAgentState
from app.services.agent.safety.budget_service import agent_budget_service
from app.services.agent.tools.registry import TOOL_REGISTRY, TOOL_SCHEMAS

logger = get_logger(__name__)

_BUILD_INTENTS = {"build_workflow", "extend_workflow", "edit_workflow", "create_sub_workflow"}


def _wrap_user_input(text: str) -> str:
    """Escapes HTML entities and wraps in XML tags to isolate untrusted user input."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<user_message>{escaped}</user_message>"


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _format_conversation_history(
    messages: list[dict[str, Any]],
    *,
    max_turns: int = 12,
    max_chars_per_turn: int = 2000,
) -> str:
    """Serializa as ultimas `max_turns` mensagens user/assistant para o planner.

    O build planner precisa do HISTORICO inteiro porque decisoes tomadas em
    turnos anteriores (ex: "quero variavel de conexao", "os DELETEs que
    listei no primeiro turno") sao obrigatorias para a construcao correta
    dos nos. Usar so a ultima mensagem fazia o planner esquecer os SQLs e
    a escolha de variavel na resposta de uma clarificacao — o motivo exato
    dos bugs relatados pelo usuario (DELETEs virando SELECT placeholder,
    variavel de conexao sendo ignorada).

    Retorno: bloco texto delimitado por tags XML, pronto para ir no payload
    JSON do user prompt. Cada mensagem fica envolta em <turn role=...>.
    Truncamos cada turn para evitar prompts gigantes em threads longas.
    """
    relevant = [
        m for m in messages
        if m.get("role") in {"user", "assistant"} and str(m.get("content") or "").strip()
    ]
    if not relevant:
        return ""
    tail = relevant[-max_turns:]
    parts: list[str] = []
    for msg in tail:
        role = msg.get("role")
        content = sanitize_llm_string(str(msg.get("content") or ""))[:max_chars_per_turn]
        # escape XML no conteudo para evitar que o usuario feche tags de turn
        escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f"<turn role=\"{role}\">{escaped}</turn>")
    return "<conversation_history>\n" + "\n".join(parts) + "\n</conversation_history>"


def _uuid_or_none(raw: Any) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


_VALID_CLARIFICATION_KINDS = {"choice", "multi_choice"}
_VALID_CLARIFICATION_FIELDS = {
    "connection_id",
    "trigger_type",
    "workflow_id",
    "target_table",
    "other",
}


def _normalize_clarification_payload(raw: Any) -> dict[str, Any] | None:
    """Valida e devolve o payload estruturado de clarification ou None.

    O LLM pode alucinar formas esquisitas; aceitamos somente o shape
    documentado e truncamos strings para evitar abuso.
    """
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in _VALID_CLARIFICATION_KINDS:
        return None

    field_raw = raw.get("field")
    field = field_raw if field_raw in _VALID_CLARIFICATION_FIELDS else "other"

    question_raw = raw.get("question")
    question = (
        sanitize_llm_string(str(question_raw).strip())[:500]
        if isinstance(question_raw, str) and question_raw.strip()
        else None
    )

    options_out: list[dict[str, Any]] = []
    for opt in raw.get("options") or []:
        if not isinstance(opt, dict):
            continue
        value = opt.get("value")
        label = opt.get("label")
        if value is None or not isinstance(label, str) or not label.strip():
            continue
        hint = opt.get("hint")
        options_out.append(
            {
                "value": sanitize_llm_string(str(value))[:200],
                "label": sanitize_llm_string(label.strip())[:120],
                "hint": (
                    sanitize_llm_string(str(hint).strip())[:200]
                    if isinstance(hint, str) and hint.strip()
                    else None
                ),
            }
        )
        if len(options_out) >= 20:
            break
    if not options_out:
        return None

    extra_raw = raw.get("extra_option")
    extra: dict[str, Any] | None = None
    if isinstance(extra_raw, dict):
        value = extra_raw.get("value")
        label = extra_raw.get("label")
        if value is not None and isinstance(label, str) and label.strip():
            extra = {
                "value": sanitize_llm_string(str(value))[:200],
                "label": sanitize_llm_string(label.strip())[:120],
                "hint": (
                    sanitize_llm_string(str(extra_raw.get("hint")).strip())[:200]
                    if isinstance(extra_raw.get("hint"), str)
                    and extra_raw.get("hint", "").strip()
                    else None
                ),
            }

    normalized: dict[str, Any] = {
        "kind": kind,
        "field": field,
        "options": options_out,
    }
    if question:
        normalized["question"] = question
    if extra:
        normalized["extra_option"] = extra
    return normalized


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


def _sql_preanalysis(user_message: str) -> dict[str, Any] | None:
    """Se a mensagem contem um bloco de SQL literal, extrai binds/tabelas para o planner.

    Conservador: so analisa quando ha um delimitador claro de SQL (bloco em
    ``` ou linha que comeca com SELECT/INSERT/... seguida de FROM/INTO/SET).
    Isso evita rodar sqlglot sobre linguagem natural que apenas menciona
    palavras como "DELETE" ou "FROM" (gerava ruido de parse errors no stderr).
    """
    import re as _re

    # 1) Bloco SQL explicito (```sql ... ``` ou ``` ... ```)
    sql_match = _re.search(r"```(?:sql)?\s*([\s\S]+?)```", user_message, _re.IGNORECASE)
    sql_snippet: str | None = sql_match.group(1).strip() if sql_match else None

    # 2) Sem bloco: exige padrao estrutural de SQL real (DML com clausula tipica)
    if sql_snippet is None:
        structural = _re.search(
            r"\b(SELECT\b[\s\S]+?\bFROM\b"
            r"|INSERT\s+INTO\b"
            r"|UPDATE\b[\s\S]+?\bSET\b"
            r"|DELETE\s+FROM\b"
            r"|MERGE\s+INTO\b"
            r"|TRUNCATE\s+TABLE\b)",
            user_message,
            _re.IGNORECASE,
        )
        if not structural:
            return None
        sql_snippet = user_message[:2000]

    if not sql_snippet:
        return None

    try:
        from app.services.agent.sql_intelligence.parser import analyze_sql_script
        return analyze_sql_script(sql_snippet)
    except Exception:  # noqa: BLE001
        return None


async def _plan_build(
    state: PlatformAgentState,
    intent_data: dict[str, Any],
    usage_prefix: str = "plan_actions_build",
) -> dict[str, Any]:
    """Chama o BUILD_PLANNER_PROMPT para intencoes de construcao de workflow."""
    all_messages = state.get("messages") or []
    user_text = sanitize_llm_string(_last_user_message(all_messages))
    ctx = state.get("user_context") or {}
    workflow_context = state.get("workflow_context") or {}

    # Pre-analise SQL considera TODAS as mensagens do usuario: o SQL pode ter
    # sido fornecido em um turno anterior (ex: usuario colou os DELETEs, depois
    # respondeu a uma clarificacao de conexao). Concatenamos os conteudos de
    # user para que o parser encontre os blocos SQL mesmo quando estao no
    # historico, nao na ultima mensagem.
    user_messages_concat = "\n\n".join(
        sanitize_llm_string(str(m.get("content") or ""))
        for m in all_messages
        if m.get("role") == "user"
    )
    sql_analysis = _sql_preanalysis(user_messages_concat or user_text)

    conversation = _format_conversation_history(all_messages)

    payload_dict: dict[str, Any] = {
        "intent": intent_data,
        "user_message": _wrap_user_input(user_text[:4000]),
        "user_context": ctx,
    }
    # O historico completo e CRITICO para multiturno: decisoes tomadas em
    # turnos anteriores (escolha de conexao vs variavel, SQLs colados antes
    # de responder uma clarificacao) precisam chegar ao planner, senao ele
    # reinterpreta a conversa do zero e perde o contexto.
    if conversation:
        payload_dict["conversation_history"] = conversation
    if workflow_context:
        wf_json = json.dumps(workflow_context, ensure_ascii=False)
        payload_dict["workflow_state"] = f"<workflow_state>{wf_json}</workflow_state>"
    if sql_analysis:
        payload_dict["sql_pre_analysis"] = sql_analysis

    user_payload = json.dumps(payload_dict, ensure_ascii=False)

    result, usage = await llm_complete_json_with_usage(
        system=BUILD_PLANNER_PROMPT,
        user=user_payload,
        fallback={"workflow_id": None, "ops": [], "summary": ""},
    )
    usage_entry = {**usage.usage_entry(), "node": usage_prefix}

    # Planner pode emitir clarification_question quando faltam decisoes chave
    # (ex: tipo de trigger, conexao a usar). Nesse caso, nao gera ops — o
    # report_node devolve a pergunta para o usuario responder.
    raw_clarification = result.get("clarification_question")
    structured = _normalize_clarification_payload(result.get("clarification"))
    if isinstance(raw_clarification, str) and raw_clarification.strip():
        question = sanitize_llm_string(raw_clarification.strip())[:500]
        if structured is not None:
            structured.setdefault("question", question)
        logger.info(
            "agent.planner.build.clarification_needed",
            thread_id=state.get("thread_id"),
            has_structured=structured is not None,
        )
        return {
            "build_plan": None,
            "proposed_actions": [],
            "clarification_question": question,
            "clarification": structured,
            "token_usage": [usage_entry],
        }

    workflow_id = result.get("workflow_id")
    if not workflow_id:
        logger.info(
            "agent.planner.build.no_workflow_id",
            thread_id=state.get("thread_id"),
        )
        return {
            "build_plan": None,
            "proposed_actions": [],
            "clarification_question": (
                "Para construir o workflow preciso saber o ID do workflow alvo. "
                "Por favor informe o workflow_id."
            ),
            "token_usage": [usage_entry],
        }

    build_plan: dict[str, Any] = {
        "workflow_id": str(workflow_id),
        "ops": result.get("ops") or [],
        "summary": str(result.get("summary") or ""),
        "intent": intent_data.get("intent"),
    }
    logger.info(
        "agent.planner.build_plan",
        thread_id=state.get("thread_id"),
        workflow_id=build_plan["workflow_id"],
        ops_count=len(build_plan["ops"]),
    )
    return {
        "build_plan": build_plan,
        "proposed_actions": [],
        "token_usage": [usage_entry],
    }


async def plan_actions_node(state: PlatformAgentState) -> dict[str, Any]:
    """Produz proposed_actions (ou build_plan) a partir da mensagem e da intencao."""
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

    intent_data = state.get("current_intent") or {"intent": "chat", "summary": ""}
    if intent_data.get("intent") in _BUILD_INTENTS:
        return await _plan_build(state, intent_data)

    user_text = sanitize_llm_string(_last_user_message(state.get("messages", [])))
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
            "intent": intent_data,
            "user_message": _wrap_user_input(user_text[:4000]),
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
