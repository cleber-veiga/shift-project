"""
Orquestracao SSE do Platform Agent.

Conecta HTTP ↔ grafo LangGraph. Traduz eventos do grafo em eventos SSE,
persiste mensagens e gerencia transicoes de status da thread.

Deteccao de interrupt: o LangGraph v0.6.x emite um evento 'on_chain_stream'
com name='LangGraph' e chunk={'__interrupt__': (Interrupt(...),)} quando
um no chama interrupt(). Este e o sinal para pausar o stream SSE e aguardar
aprovacao humana via POST separado.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Any, Literal
from uuid import UUID

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import authorization_service
from app.models.agent_thread import AgentThread
from app.models import User
from app.models.workspace import Workspace
from app.services.agent.context import UserContext
from app.services.agent.events import (
    EVT_APPROVAL_REQUIRED,
    EVT_CLARIFICATION,
    EVT_DELTA,
    EVT_DONE,
    EVT_ERROR,
    EVT_GUARDRAILS_REFUSE,
    EVT_INTENT_DETECTED,
    EVT_META,
    EVT_PLAN_PROPOSED,
    EVT_THINKING,
    EVT_TOOL_CALL_END,
    EVT_TOOL_CALL_START,
    sse_event,
)
from app.services.agent.graph.builder import build_graph
from app.services.agent.graph.checkpointer import get_checkpointer
from app.services.agent.thread_service import thread_service

logger = get_logger(__name__)

_TOOL_CALL_PREVIEW = 500


def _synthesize_interrupt_placeholder(
    *,
    current_intent: dict[str, Any] | None,
    interrupt_payload: dict[str, Any] | None,
    build_plan: dict[str, Any] | None,
) -> str:
    """Gera um texto curto de assistente para salvar quando o grafo e suspenso.

    O texto precisa transmitir, ao reabrir a conversa, em que ponto a
    interacao parou — aguardando aprovacao de SQL destrutivo, aguardando
    confirmacao de build, etc. Nao substitui o final_report (que viria do
    report_node apos a conclusao), mas serve como ancora de contexto.
    """
    interrupt_type = (interrupt_payload or {}).get("type")
    plan = (interrupt_payload or {}).get("plan") or {}
    summary = str(plan.get("summary") or "").strip()
    impact = str(plan.get("impact") or "").strip()

    if interrupt_type == "build_ready":
        nodes = len((interrupt_payload or {}).get("pending_nodes") or [])
        edges = len((interrupt_payload or {}).get("pending_edges") or [])
        plan_summary = str((build_plan or {}).get("summary") or "").strip()
        parts = ["Proposta de construcao aguardando sua confirmacao no canvas."]
        if plan_summary:
            parts.append(plan_summary)
        if nodes or edges:
            parts.append(f"{nodes} no(s) e {edges} conexao(oes) pendentes.")
        return " ".join(parts)

    if interrupt_type in {"approval_required", None} and plan:
        parts = []
        if summary:
            parts.append(summary)
        if impact:
            parts.append(f"Impacto: {impact}")
        parts.append("Aguardando sua aprovacao para prosseguir.")
        return " ".join(parts)

    intent_name = str((current_intent or {}).get("intent") or "").strip()
    if intent_name in {"build_workflow", "create_sub_workflow", "extend_workflow"}:
        return "Plano de construcao gerado — aguardando proxima etapa."
    return "Execucao pausada aguardando uma decisao."


def _to_frontend_plan(
    intent_data: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Converte proposed_actions internas para o formato esperado pelo frontend."""
    current_intent = intent_data or {}
    planned_actions = actions or []
    summary = str(current_intent.get("summary") or "").strip()
    intent = str(current_intent.get("intent") or "ação")

    steps = [
        {
            "step": index + 1,
            "description": action.get("rationale")
            or f"Executar {action.get('tool') or 'ação'}",
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

    impact_parts = []
    if any(
        tc.get("requires_approval")
        for action in planned_actions
        if isinstance(action, dict)
        for tc in [action]
    ):
        impact_parts.append("Pode exigir aprovação antes de executar.")
    if planned_actions:
        impact_parts.append(f"{len(planned_actions)} ação(ões) planejada(s).")

    return {
        "intent": intent,
        "summary": summary or "Plano de ação sugerido pelo agente.",
        "impact": " ".join(impact_parts),
        "steps": steps,
    }


async def _build_user_context(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: UUID,
    project_id: UUID | None,
) -> UserContext:
    """Resolve roles efetivos do usuario e constroi UserContext imutavel."""
    from sqlalchemy import select
    from app.models.workspace import Workspace as WS
    from app.models import (
        WorkspaceMember,
        OrganizationMember,
        ProjectMember,
    )
    from app.core.security import compute_effective_ws_role, compute_effective_project_role

    ws_result = await db.execute(
        select(WS).where(WS.id == workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    org_id = workspace.organization_id if workspace else None

    # Resolve org role
    from app.models import OrganizationRole, WorkspaceRole
    org_role = None
    if org_id is not None:
        org_role = await db.scalar(
            select(OrganizationMember.role).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )

    # Resolve workspace role
    ws_explicit = await db.scalar(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    effective_ws, _ = compute_effective_ws_role(org_role, ws_explicit)
    ws_role_str = effective_ws.value if effective_ws else "VIEWER"

    # Resolve project role
    proj_role_str: str | None = None
    if project_id is not None:
        from app.models import ProjectRole
        proj_explicit = await db.scalar(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user.id,
            )
        )
        from app.core.security import compute_effective_project_role as _cep
        effective_proj, _ = _cep(org_role, effective_ws, proj_explicit)
        proj_role_str = effective_proj.value if effective_proj else None

    return UserContext(
        user_id=user.id,
        workspace_id=workspace_id,
        project_id=project_id,
        workspace_role=ws_role_str,
        project_role=proj_role_str,
        organization_id=org_id or workspace_id,
        organization_role=org_role.value if org_role else None,
    )


def _ctx_to_dict(ctx: UserContext) -> dict[str, Any]:
    d = asdict(ctx)
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in d.items()}


async def _get_graph():
    checkpointer = await get_checkpointer()
    return build_graph(checkpointer=checkpointer)


def _extract_execute_details(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrai executed_actions do output do no execute."""
    return output.get("executed_actions") or []


def _aggregate_token_usage(
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Soma entradas de token_usage para persistir em agent_messages.msg_metadata."""
    if not entries:
        return None
    prompt = 0
    completion = 0
    model = ""
    per_node: list[dict[str, Any]] = []
    for entry in entries:
        prompt += int(entry.get("prompt_tokens", 0) or 0)
        completion += int(entry.get("completion_tokens", 0) or 0)
        if not model and entry.get("model"):
            model = str(entry.get("model"))
        per_node.append(
            {
                "node": entry.get("node"),
                "prompt_tokens": int(entry.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(entry.get("completion_tokens", 0) or 0),
                "total_tokens": int(entry.get("total_tokens", 0) or 0),
            }
        )
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "model": model,
        "per_node": per_node,
    }


class AgentChatService:
    """Orquestra invocacao do grafo e streaming SSE de eventos."""

    async def stream_message(
        self,
        *,
        db: AsyncSession,
        thread: AgentThread,
        user: User,
        message: str,
        screen_context: dict[str, Any] | None,
    ) -> AsyncGenerator[str, None]:
        """Envia mensagem do usuario ao grafo e transmite eventos SSE."""
        return self._stream_message_impl(
            db=db,
            thread=thread,
            user=user,
            message=message,
            screen_context=screen_context,
        )

    async def _stream_message_impl(
        self,
        *,
        db: AsyncSession,
        thread: AgentThread,
        user: User,
        message: str,
        screen_context: dict[str, Any] | None,
    ) -> AsyncGenerator[str, None]:
        yield sse_event(EVT_META, {"model": settings.AGENT_LLM_MODEL})

        try:
            await thread_service.add_message(
                db,
                thread_id=thread.id,
                role="user",
                content=message,
            )
        except Exception:
            logger.exception("agent.chat.persist_user_msg_failed", thread_id=str(thread.id))
            yield sse_event(EVT_ERROR, {"message": "Erro ao salvar mensagem."})
            return

        try:
            ctx = await _build_user_context(
                db,
                user=user,
                workspace_id=thread.workspace_id,
                project_id=thread.project_id,
            )
        except Exception:
            logger.exception("agent.chat.build_context_failed", thread_id=str(thread.id))
            yield sse_event(EVT_ERROR, {"message": "Erro ao construir contexto do usuario."})
            return

        initial_state = {
            "thread_id": str(thread.id),
            "user_context": _ctx_to_dict(ctx),
            "messages": [{"role": "user", "content": message}],
            "executed_actions": [],
        }
        if screen_context:
            initial_state["user_context"]["screen_context"] = screen_context

        config = {"configurable": {"thread_id": str(thread.id)}}

        try:
            graph = await _get_graph()
        except Exception:
            logger.exception("agent.chat.get_graph_failed")
            yield sse_event(EVT_ERROR, {"message": "Erro ao inicializar o agente."})
            return

        async for chunk in self._run_stream(graph, initial_state, config, db, thread):
            yield chunk

    async def stream_resume(
        self,
        *,
        db: AsyncSession,
        thread: AgentThread,
        user: User,
        decision: Literal["approved", "rejected"],
        approval_id: UUID,
        reason: str | None,
    ) -> AsyncGenerator[str, None]:
        """Retoma o grafo apos decisao humana e transmite eventos SSE."""
        return self._stream_resume_impl(
            db=db,
            thread=thread,
            user=user,
            decision=decision,
            approval_id=approval_id,
            reason=reason,
        )

    async def _stream_resume_impl(
        self,
        *,
        db: AsyncSession,
        thread: AgentThread,
        user: User,
        decision: Literal["approved", "rejected"],
        approval_id: UUID,
        reason: str | None,
    ) -> AsyncGenerator[str, None]:
        yield sse_event(EVT_META, {"model": settings.AGENT_LLM_MODEL, "resuming": True})

        approved = decision == "approved"
        resume_payload = {
            "approved": approved,
            "decided_by": str(user.id),
            "rejection_reason": reason,
        }
        command = Command(resume=resume_payload)
        config = {"configurable": {"thread_id": str(thread.id)}}

        try:
            graph = await _get_graph()
        except Exception:
            logger.exception("agent.chat.get_graph_failed_resume")
            yield sse_event(EVT_ERROR, {"message": "Erro ao inicializar o agente."})
            return

        async for chunk in self._run_stream(graph, command, config, db, thread):
            yield chunk

    async def _run_stream(
        self,
        graph: Any,
        input_: Any,
        config: dict[str, Any],
        db: AsyncSession,
        thread: AgentThread,
    ) -> AsyncGenerator[str, None]:
        """Iteracao sobre astream_events e traducao para SSE."""
        final_report: str | None = None
        interrupted = False
        token_usage_entries: list[dict[str, Any]] = []
        current_intent: dict[str, Any] | None = (
            input_.get("current_intent") if isinstance(input_, dict) else None
        )
        # Metadados capturados durante o stream — usados para persistir uma
        # mensagem de assistente mesmo quando o grafo e suspenso por interrupt,
        # de modo que ao reabrir a conversa o usuario veja o contexto (plano
        # proposto, build em andamento, etc.) em vez de apenas o prompt dele.
        last_interrupt_payload: dict[str, Any] | None = None
        last_build_plan: dict[str, Any] | None = None
        # Clarification estruturada emitida pelo planner quando falta um dado
        # que so o usuario pode responder (conexao alvo, tipo de trigger, ...).
        # Guardamos para: (a) emitir EVT_CLARIFICATION como evento dedicado
        # alem do texto em final_report; (b) persistir em msg_metadata para
        # que a thread reabra renderizando o card de selecao em vez de
        # perguntar novamente.
        last_clarification: dict[str, Any] | None = None
        last_clarification_question: str | None = None

        try:
            async for event in graph.astream_events(input_, version="v2", config=config):
                evt_name = event.get("event", "")
                node_name = event.get("name", "")
                data = event.get("data") or {}

                # --- thinking: no comecarou ---
                if evt_name == "on_chain_start" and node_name in {
                    "guardrails",
                    "understand_intent",
                    "plan_actions",
                    "human_approval",
                    "execute",
                    "report",
                    "build_workflow",
                }:
                    yield sse_event(EVT_THINKING, {"node": node_name})

                # --- detectar interrupt ---
                elif (
                    evt_name == "on_chain_stream"
                    and node_name == "LangGraph"
                    and "__interrupt__" in (data.get("chunk") or {})
                ):
                    interrupted = True
                    interrupts = data["chunk"]["__interrupt__"]
                    payload = interrupts[0].value if interrupts else {}
                    interrupt_type = payload.get("type")

                    # O nó build_workflow usa DOIS interrupts distintos:
                    #   - "approval_required": aprovacao humana de acao sensivel
                    #     (ex: SQL destrutivo) — precisa aparecer no chat com
                    #     plano + botoes de aprovar/rejeitar.
                    #   - "build_ready": pausa aguardando o usuario confirmar
                    #     a aplicacao dos ghost nodes/edges no canvas. Esse
                    #     gate ja e tratado pelo BuildModeContext (via canal
                    #     SSE de workflow_definition_events + AIBuildConfirmationCard).
                    #     Se emitissemos approval_required aqui, o frontend
                    #     criaria um card fantasma com plan=null (cai no
                    #     placeholder "INTENCAO acao" e "Aguardando" eterno
                    #     porque nao ha approval_id para resolver).
                    if interrupt_type == "build_ready":
                        # Nao emite approval_required; o card de confirmacao
                        # sera renderizado pelo BuildModeContext quando o
                        # estado passar para awaiting_confirmation. Ainda
                        # precisamos marcar a thread para o cliente saber
                        # que o stream nao continuara ate ter uma decisao.
                        last_interrupt_payload = payload
                        try:
                            await thread_service.update_status(
                                db,
                                thread_id=thread.id,
                                status_value="awaiting_approval",
                            )
                        except Exception:
                            logger.exception(
                                "agent.chat.status_update_failed",
                                thread_id=str(thread.id),
                            )
                        continue

                    approval_id = payload.get("approval_id")
                    last_interrupt_payload = payload
                    yield sse_event(
                        EVT_APPROVAL_REQUIRED,
                        {"approval_id": approval_id, "plan": payload.get("plan")},
                    )
                    try:
                        await thread_service.update_status(
                            db,
                            thread_id=thread.id,
                            status_value="awaiting_approval",
                        )
                    except Exception:
                        logger.exception("agent.chat.status_update_failed", thread_id=str(thread.id))

                # --- saida do no guardrails ---
                elif evt_name == "on_chain_end" and node_name == "guardrails":
                    output = data.get("output") or {}
                    violation = output.get("guardrails_violation")
                    if violation:
                        yield sse_event(EVT_GUARDRAILS_REFUSE, {"reason": violation})

                # --- saida do no understand_intent ---
                elif evt_name == "on_chain_end" and node_name == "understand_intent":
                    output = data.get("output") or {}
                    intent_data = output.get("current_intent") or {}
                    current_intent = intent_data
                    if intent_data:
                        yield sse_event(
                            EVT_INTENT_DETECTED,
                            {
                                "intent": intent_data.get("intent"),
                                "description": intent_data.get("summary"),
                            },
                        )

                # --- saida do no plan_actions ---
                elif evt_name == "on_chain_end" and node_name == "plan_actions":
                    output = data.get("output") or {}
                    actions = output.get("proposed_actions") or []
                    build_plan = output.get("build_plan")
                    if isinstance(build_plan, dict):
                        last_build_plan = build_plan
                    clar_question = output.get("clarification_question")
                    clar_payload = output.get("clarification")
                    if isinstance(clar_question, str) and clar_question.strip():
                        last_clarification_question = clar_question
                        if isinstance(clar_payload, dict):
                            last_clarification = clar_payload
                        # Emite evento dedicado para que a UI renderize
                        # chips/botoes ao inves de so mostrar texto. O delta
                        # com a pergunta ainda sera enviado quando o
                        # report_node concluir.
                        yield sse_event(
                            EVT_CLARIFICATION,
                            {
                                "question": clar_question,
                                "clarification": clar_payload
                                if isinstance(clar_payload, dict)
                                else None,
                            },
                        )
                    if actions:
                        yield sse_event(
                            EVT_PLAN_PROPOSED,
                            {"plan": _to_frontend_plan(current_intent, actions)},
                        )

                # --- saida do no execute (tool calls individuais) ---
                elif evt_name == "on_chain_end" and node_name == "execute":
                    output = data.get("output") or {}
                    for i, action in enumerate(_extract_execute_details(output)):
                        yield sse_event(
                            EVT_TOOL_CALL_START,
                            {
                                "step": i,
                                "tool_name": action.get("tool"),
                                "arguments": action.get("arguments"),
                            },
                        )
                        yield sse_event(
                            EVT_TOOL_CALL_END,
                            {
                                "step": i,
                                "tool_name": action.get("tool"),
                                "success": action.get("status") == "success",
                                "preview": action.get("preview"),
                                "duration_ms": action.get("duration_ms"),
                                "error": action.get("error"),
                            },
                        )

                # --- saida do no report (final) ---
                elif evt_name == "on_chain_end" and node_name == "report":
                    output = data.get("output") or {}
                    final_report = output.get("final_report") or ""
                    if final_report:
                        yield sse_event(EVT_DELTA, {"text": final_report})

                # --- acumula token_usage reportado por qualquer no ---
                if evt_name == "on_chain_end" and node_name in {
                    "guardrails",
                    "understand_intent",
                    "plan_actions",
                    "report",
                }:
                    output = data.get("output") or {}
                    for entry in output.get("token_usage") or []:
                        if isinstance(entry, dict):
                            token_usage_entries.append(entry)

        except Exception:
            logger.exception("agent.chat.stream_failed", thread_id=str(thread.id))
            try:
                await thread_service.update_status(
                    db, thread_id=thread.id, status_value="error"
                )
            except Exception:
                pass
            yield sse_event(EVT_ERROR, {"message": "Erro interno no agente."})
            return

        if not interrupted:
            if final_report:
                metadata = _aggregate_token_usage(token_usage_entries)
                # Quando o turno terminou em uma pergunta de clarificacao
                # com opcoes estruturadas, preservamos o payload em
                # msg_metadata para que o frontend rehidrate o card de
                # selecao ao reabrir a conversa (e nao apenas o texto).
                if last_clarification is not None or last_clarification_question:
                    metadata = {
                        **(metadata or {}),
                        "clarification": last_clarification,
                        "clarification_question": last_clarification_question,
                    }
                try:
                    await thread_service.add_message(
                        db,
                        thread_id=thread.id,
                        role="assistant",
                        content=final_report,
                        msg_metadata=metadata,
                    )
                except Exception:
                    logger.exception(
                        "agent.chat.persist_assistant_msg_failed",
                        thread_id=str(thread.id),
                    )

            final_status = "completed"
            try:
                await thread_service.update_status(
                    db, thread_id=thread.id, status_value=final_status
                )
            except Exception:
                logger.exception(
                    "agent.chat.final_status_failed", thread_id=str(thread.id)
                )

            yield sse_event(EVT_DONE, {"thread_status": final_status})
        else:
            # Grafo suspenso por interrupt() (ex.: aprovacao humana). O status
            # ja foi atualizado para awaiting_approval junto ao approval_required.
            # Ainda assim precisamos sinalizar fim de stream para o cliente sair
            # do estado isStreaming/thinking; caso contrario a UI fica com
            # spinner eterno aguardando um `done` que nao vem.

            # Persistimos uma mensagem de assistente mesmo sem final_report: em
            # build flows o report_node nunca roda (build_workflow fica pausado
            # no interrupt e a confirmacao acontece via POST /confirm, fora do
            # grafo). Sem isso, ao reabrir a conversa o usuario veria apenas o
            # proprio prompt, perdendo completamente o contexto do plano, do
            # build em andamento e das aprovacoes ja emitidas.
            try:
                placeholder = _synthesize_interrupt_placeholder(
                    current_intent=current_intent,
                    interrupt_payload=last_interrupt_payload,
                    build_plan=last_build_plan,
                )
                metadata = _aggregate_token_usage(token_usage_entries)
                if last_interrupt_payload is not None:
                    # Guardamos o payload do interrupt nos metadados para que o
                    # frontend possa reconstruir o card (plano destrutivo, build
                    # em andamento) ao recarregar a thread, alem do ja existente
                    # pending_approval que decorra a ultima mensagem.
                    metadata = {
                        **(metadata or {}),
                        "interrupt": {
                            "type": last_interrupt_payload.get("type"),
                            "approval_id": last_interrupt_payload.get("approval_id"),
                            "plan": last_interrupt_payload.get("plan"),
                            "session_id": last_interrupt_payload.get("session_id"),
                            "workflow_id": last_interrupt_payload.get("workflow_id"),
                        },
                    }
                if last_build_plan is not None:
                    metadata = {**(metadata or {}), "build_plan": last_build_plan}
                await thread_service.add_message(
                    db,
                    thread_id=thread.id,
                    role="assistant",
                    content=placeholder,
                    msg_metadata=metadata,
                )
            except Exception:
                logger.exception(
                    "agent.chat.persist_interrupted_msg_failed",
                    thread_id=str(thread.id),
                )

            yield sse_event(EVT_DONE, {"thread_status": "awaiting_approval"})


agent_chat_service = AgentChatService()
