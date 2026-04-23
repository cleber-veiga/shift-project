"""No de construcao de workflow em build mode (FASE 4/5).

Fluxo:
  1. Le build_plan produzido pelo plan_actions_node.
  2. Valida: workflow_id presente, ops <= 50, sem SQL destrutivo, budget ok.
  3. Cria BuildSession (com auditoria).
  4. Calcula layout automatico para os nos pendentes.
  5. Analisa sql_script nodes via SQL Intelligence.
  6. Despacha ops pelo dispatcher de pending_* tools, publicando eventos SSE.
  7. Sinaliza build_ready e pausa o grafo com interrupt().
  8. Ao retornar:
     - action == "confirm" -> chama build_session_service.confirm() inline.
     - action == "cancel"  -> cancela sessao, publica build_cancelled.
  9. Escreve entrada de auditoria no agent_audit_log (se thread_id disponivel).

Formatos de op suportados:
  Novo (FASE 5): {"tool": "pending_add_node", "arguments": {"temp_id": ..., ...}}
  Legado:        {"op": "add_node", "node_type": ..., "label": ..., "config": ...}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langgraph.types import interrupt

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.layout import compute_layout
from app.services.agent.graph.nodes.human_approval import request_human_approval
from app.services.agent.graph.state import PlatformAgentState
from app.services.agent.sql_intelligence.parser import analyze_sql_script
from app.services.agent.tools.workflow_pending_tools import (
    pending_add_edge,
    pending_add_node,
    pending_remove_node,
    pending_set_io_schema,
    pending_set_variables,
    pending_update_node,
)
from app.services.build_session_service import BuildSessionNotFoundError, build_session_service
from app.services.definition_event_service import definition_event_service

logger = get_logger(__name__)

_MAX_OPS = 50

_PENDING_DISPATCH: dict[str, Any] = {
    "pending_add_node": pending_add_node,
    "pending_add_edge": pending_add_edge,
    "pending_update_node": pending_update_node,
    "pending_remove_node": pending_remove_node,
    "pending_set_variables": pending_set_variables,
    "pending_set_io_schema": pending_set_io_schema,
}


def _enrich_sql_node_data(op: dict[str, Any]) -> dict[str, Any]:
    """Roda SQL Intelligence no sql_script e injeta analise no data do no.

    O campo canonico no `data` do no sql_script e `script` (conforme
    frontend SqlScriptConfig e backend sql_script.py). Versoes antigas
    do prompt/agente usavam `query` — aceitamos ambos e normalizamos
    promovendo `query -> script` quando so `query` estiver presente,
    para evitar nos chegarem vazios no canvas.
    """
    config = dict(op.get("config") or {})
    script = str(config.get("script") or "").strip()
    legacy_query = str(config.get("query") or "").strip()
    if not script and legacy_query:
        script = legacy_query
        config["script"] = legacy_query
        config.pop("query", None)
    if not script:
        return config

    try:
        analysis = analyze_sql_script(script)
        config["_sql_analysis"] = {
            "destructiveness": analysis["destructiveness"],
            "tables": analysis["tables"],
            "binds": analysis["binds"],
            "statement_count": analysis["statement_count"],
        }
        if analysis["suggested_input_schema"] and "_input_schema" not in config:
            config["_input_schema"] = analysis["suggested_input_schema"]
    except Exception:  # noqa: BLE001
        pass  # Analise e best-effort; nao bloqueia
    return config


async def _write_audit(
    *,
    thread_id: str | None,
    user_id: str | None,
    session_id: str,
    workflow_id: str,
    build_plan: dict[str, Any],
    operations_applied: list[dict[str, Any]],
    status: str,
    total_tokens: int,
    duration_ms: int,
    user_prompt: str | None = None,
) -> None:
    """Escreve auditoria no agent_audit_log se thread_id disponivel."""
    if not thread_id or not user_id:
        return
    try:
        from uuid import UUID as _UUID
        from app.services.agent.persistence import write_audit_log
        async with async_session_factory() as db:
            await write_audit_log(
                db,
                thread_id=_UUID(thread_id),
                user_id=_UUID(user_id),
                tool_name="build_workflow_session",
                tool_arguments={"workflow_id": workflow_id, "session_id": session_id},
                status=status,
                log_metadata={
                    "generated_plan": build_plan,
                    "operations_applied": operations_applied,
                    "total_tokens": total_tokens,
                    "duration_ms": duration_ms,
                    "session_id": session_id,
                    "user_prompt": user_prompt,
                },
            )
    except Exception:  # noqa: BLE001
        logger.exception("agent.build_workflow.audit_write_failed", session_id=session_id)


def _is_new_format(ops: list[dict[str, Any]]) -> bool:
    """Retorna True se qualquer op usa o formato novo FASE 5 {tool, arguments}."""
    return bool(ops) and any("tool" in op for op in ops)


async def _dispatch_pending_tool(
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Despacha uma pending tool e retorna o resultado parseado como dict."""
    func = _PENDING_DISPATCH.get(tool_name)
    if func is None:
        return {"error": {"code": "UNKNOWN_TOOL", "message": f"Tool '{tool_name}' nao registrada."}}
    try:
        result_json = await func(db=None, ctx=None, **args)
        return json.loads(result_json)
    except Exception as exc:  # noqa: BLE001
        return {"error": {"code": "TOOL_ERROR", "message": str(exc)}}


async def _run_new_format_ops(
    ops: list[dict[str, Any]],
    *,
    session_id: UUID,
    workflow_id: UUID,
) -> tuple[int, int]:
    """Despacha ops no formato novo (FASE 5) e retorna (nodes_added, edges_added)."""

    # Preparar adapter para compute_layout: usa temp_id como label
    node_layout_ops: list[dict[str, Any]] = []
    edge_layout_ops: list[dict[str, Any]] = []

    for op in ops:
        tool = op.get("tool", "")
        args = op.get("arguments", {})
        if tool == "pending_add_node":
            node_layout_ops.append({
                "label": args.get("temp_id") or args.get("node_type") or "node",
                "node_type": args.get("node_type", ""),
            })
        elif tool == "pending_add_edge":
            edge_layout_ops.append({
                "source_label": args.get("source_temp_id", ""),
                "target_label": args.get("target_temp_id", ""),
            })

    positions = compute_layout(node_layout_ops, edge_layout_ops)

    # Mapa: temp_id -> posicao calculada
    pos_map: dict[str, dict[str, float]] = {}
    node_idx = 0
    for op in ops:
        if op.get("tool") == "pending_add_node":
            args = op.get("arguments", {})
            temp_id = args.get("temp_id", "")
            if node_idx < len(positions):
                pos_map[temp_id] = positions[node_idx]
            node_idx += 1

    nodes_added = 0
    edges_added = 0
    sid_str = str(session_id)

    for op in ops:
        tool = op.get("tool", "")
        if tool not in _PENDING_DISPATCH:
            logger.warning(
                "agent.build_workflow.unknown_tool",
                tool=tool,
                session_id=sid_str,
            )
            continue

        args = dict(op.get("arguments", {}))
        args["session_id"] = sid_str

        # Enrich sql_script com SQL Intelligence antes de despachar
        if tool == "pending_add_node" and args.get("node_type") == "sql_script":
            enriched_config = _enrich_sql_node_data({"config": args.get("config") or {}})
            args["config"] = enriched_config

        # Injeta posicao calculada se ausente
        if tool == "pending_add_node" and "position" not in args:
            temp_id = args.get("temp_id", "")
            if temp_id in pos_map:
                args["position"] = pos_map[temp_id]

        result = await _dispatch_pending_tool(tool, args)

        if "error" in result:
            logger.warning(
                "agent.build_workflow.tool_error",
                tool=tool,
                error=result["error"],
                session_id=sid_str,
            )
        elif tool == "pending_add_node":
            nodes_added += 1
        elif tool == "pending_add_edge":
            edges_added += 1

    return nodes_added, edges_added


async def _run_legacy_ops(
    ops: list[dict[str, Any]],
    *,
    session_id: UUID,
    workflow_id: UUID,
) -> tuple[int, int]:
    """Executa ops no formato legado {op: add_node/add_edge}."""

    node_ops = [op for op in ops if op.get("op") == "add_node"]
    edge_ops = [op for op in ops if op.get("op") == "add_edge"]

    # Enrich sql_script nodes
    enriched_node_ops = []
    for op in node_ops:
        enriched = dict(op)
        if op.get("node_type") == "sql_script":
            enriched = {**op, "config": _enrich_sql_node_data(op)}
        enriched_node_ops.append(enriched)

    positions = compute_layout(enriched_node_ops, edge_ops)

    label_to_node_id: dict[str, str] = {}

    for i, op in enumerate(enriched_node_ops):
        node_type_val = op.get("node_type")
        if not node_type_val:
            logger.warning(
                "agent.build_workflow.missing_node_type",
                op_index=i,
                op=op,
                session_id=str(session_id),
            )
            return {
                "guardrails_violation": "LLM omitiu node_type em uma op de no.",
                "final_report": json.dumps({
                    "code": "invalid_plan",
                    "message": "LLM omitiu node_type em uma op de no.",
                }),
            }
        label = str(op.get("label") or node_type_val)
        data: dict[str, Any] = {"label": label, **(op.get("config") or {})}
        pos = positions[i] if i < len(positions) else {"x": float(i * 270 + 120), "y": 120.0}

        node = await build_session_service.add_pending_node(
            session_id,
            node_type=str(node_type_val),
            position=pos,
            data=data,
        )
        if node:
            label_to_node_id[label] = node.node_id
            async with async_session_factory() as db:
                await definition_event_service.publish(
                    db,
                    workflow_id=workflow_id,
                    event_type="pending_node_added",
                    payload={"node": node.to_dict()},
                )

    for edge_op in edge_ops:
        src_label = str(edge_op.get("source_label") or "")
        tgt_label = str(edge_op.get("target_label") or "")
        source_id = label_to_node_id.get(src_label)
        target_id = label_to_node_id.get(tgt_label)

        if not source_id or not target_id:
            logger.warning(
                "agent.build_workflow.edge_label_not_found",
                src_label=src_label,
                tgt_label=tgt_label,
                session_id=str(session_id),
            )
            continue

        edge = await build_session_service.add_pending_edge(
            session_id,
            source=source_id,
            target=target_id,
            source_handle=edge_op.get("source_handle") or None,
            target_handle=edge_op.get("target_handle") or None,
        )
        if edge:
            async with async_session_factory() as db:
                await definition_event_service.publish(
                    db,
                    workflow_id=workflow_id,
                    event_type="pending_edge_added",
                    payload={"edge": edge.to_dict()},
                )

    confirmed_edges = sum(
        1
        for e in edge_ops
        if label_to_node_id.get(str(e.get("source_label") or ""))
        and label_to_node_id.get(str(e.get("target_label") or ""))
    )
    return len(label_to_node_id), confirmed_edges


async def build_workflow_node(state: PlatformAgentState) -> dict[str, Any]:
    """Orquestra a criacao de nos/arestas ghost e aguarda confirmacao do usuario."""
    started_at = datetime.now(timezone.utc)
    build_plan: dict[str, Any] = state.get("build_plan") or {}
    workflow_id_raw = build_plan.get("workflow_id")

    if not workflow_id_raw:
        return {
            "final_report": (
                "Nao foi possivel identificar o workflow alvo. "
                "Por favor, informe o workflow_id."
            ),
        }

    try:
        workflow_id = UUID(str(workflow_id_raw))
    except (TypeError, ValueError):
        return {"final_report": "O workflow_id informado nao e um UUID valido."}

    ops: list[dict[str, Any]] = build_plan.get("ops") or []
    summary: str = build_plan.get("summary") or ""
    ctx = state.get("user_context") or {}
    user_id_raw = ctx.get("user_id")
    thread_id = state.get("thread_id")
    messages: list[dict[str, Any]] = state.get("messages") or []
    user_prompt: str | None = None
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content")
            user_prompt = str(content) if content else None
            break

    # --- Budget check ---
    if user_id_raw:
        ok, budget_reason = build_session_service.check_build_budget(str(user_id_raw))
        if not ok:
            return {"final_report": budget_reason, "guardrails_violation": budget_reason}

    # --- Guardrail: op count ---
    if len(ops) > _MAX_OPS:
        reason = f"Plano excede limite de {_MAX_OPS} ops ({len(ops)} solicitadas)."
        logger.warning(
            "agent.build_workflow.ops_budget_exceeded",
            workflow_id=str(workflow_id),
            ops_count=len(ops),
            thread_id=thread_id,
        )
        return {
            "guardrails_violation": reason,
            "final_report": (
                f"O plano gerado tem {len(ops)} operacoes, "
                f"mas o limite por sessao e {_MAX_OPS}. "
                "Divida o plano em partes menores."
            ),
        }

    # --- Guardrail: destructive SQL (interrupt para aprovacao humana) ---
    destructive_tables: list[str] = []
    for op in ops:
        if op.get("op") == "add_node" or op.get("tool") == "pending_add_node":
            args = op.get("arguments") or op
            if args.get("node_type") == "sql_script":
                cfg = args.get("config") or {}
                # Aceita tanto "script" (campo canonico) quanto "query" (legacy
                # em prompts antigos). Normalizacao completa ocorre em
                # _enrich_sql_node_data.
                script_sql = str(cfg.get("script") or cfg.get("query") or "")
                if script_sql:
                    try:
                        analysis = analyze_sql_script(script_sql)
                        if analysis.get("destructiveness") in ("destructive", "schema_change"):
                            tables = [
                                t.get("table")
                                for t in (analysis.get("tables") or [])
                                if t.get("table")
                            ]
                            destructive_tables.extend(tables)
                    except Exception:  # noqa: BLE001
                        pass

    if destructive_tables:
        unique_tables = sorted(set(destructive_tables))
        tables_str = ", ".join(unique_tables) or "desconhecidas"
        logger.warning(
            "agent.build_workflow.destructive_sql_requires_approval",
            workflow_id=str(workflow_id),
            tables=unique_tables,
            thread_id=thread_id,
        )

        if not thread_id:
            # Sem thread nao ha registro de aprovacao possivel em agent_approvals.
            return {
                "guardrails_violation": (
                    "SQL destrutivo detectado mas nenhuma thread disponivel "
                    "para registrar a aprovacao."
                ),
                "final_report": (
                    "Construcao abortada: o plano contem SQL destrutivo e "
                    "nao foi possivel solicitar aprovacao (thread ausente)."
                ),
            }

        destructive_plan = {
            "intent": "build_workflow",
            "summary": (
                f"Aprovacao necessaria: o plano contem SQL destrutivo "
                f"em {len(unique_tables)} tabela(s): {tables_str}."
            ),
            "impact": (
                f"Operacoes destrutivas (DELETE/TRUNCATE/DROP) serao aplicadas "
                f"em: {tables_str}. Dados afetados nao poderao ser recuperados."
            ),
            "steps": [
                {
                    "step": idx + 1,
                    "description": f"SQL destrutivo afetando {table}",
                    "tool_calls": [
                        {
                            "tool_name": "pending_add_node",
                            "arguments": {"destructive_table": table},
                            "rationale": (
                                "Operacao destrutiva requer aprovacao humana "
                                "antes da construcao prosseguir."
                            ),
                            "requires_approval": True,
                        }
                    ],
                }
                for idx, table in enumerate(unique_tables)
            ],
        }

        try:
            approved, approval_id, rejection = await request_human_approval(
                thread_id=thread_id,
                plan_payload=destructive_plan,
                user_id_fallback=str(user_id_raw) if user_id_raw else None,
            )
        except (TypeError, ValueError) as exc:
            logger.exception(
                "agent.build_workflow.destructive_approval_failed",
                workflow_id=str(workflow_id),
                thread_id=thread_id,
            )
            return {
                "guardrails_violation": (
                    f"Falha ao solicitar aprovacao humana para SQL destrutivo: {exc}"
                ),
                "final_report": (
                    "Construcao abortada: nao foi possivel registrar a "
                    "aprovacao do SQL destrutivo."
                ),
            }

        if not approved:
            reason_suffix = f" Motivo: {rejection}" if rejection else ""
            logger.info(
                "agent.build_workflow.destructive_sql_rejected",
                workflow_id=str(workflow_id),
                thread_id=thread_id,
                approval_id=approval_id,
            )
            return {
                "guardrails_violation": "SQL destrutivo nao aprovado pelo usuario.",
                "final_report": (
                    "Construcao abortada: o plano contem SQL destrutivo "
                    f"nao aprovado.{reason_suffix}"
                ).strip(),
            }

        logger.info(
            "agent.build_workflow.destructive_sql_approved",
            workflow_id=str(workflow_id),
            thread_id=thread_id,
            approval_id=approval_id,
            tables=unique_tables,
        )

    # --- Create build session ---
    session = await build_session_service.create(
        workflow_id=workflow_id,
        user_id=str(user_id_raw) if user_id_raw else None,
    )
    session_id = session.session_id

    await build_session_service.set_audit(
        session_id,
        {
            "user_id": str(user_id_raw) if user_id_raw else None,
            "workflow_id": str(workflow_id),
            "thread_id": thread_id,
            "generated_plan": build_plan,
            "started_at": started_at.isoformat(),
        },
    )

    async with async_session_factory() as db:
        await definition_event_service.publish(
            db,
            workflow_id=workflow_id,
            event_type="build_started",
            payload={"session_id": str(session_id), "reason": summary},
        )

    logger.info(
        "agent.build_workflow.session_created",
        session_id=str(session_id),
        workflow_id=str(workflow_id),
        ops_count=len(ops),
        format="new" if _is_new_format(ops) else "legacy",
        thread_id=thread_id,
    )

    # --- Dispatch ops ---
    if _is_new_format(ops):
        confirmed_nodes, confirmed_edges = await _run_new_format_ops(
            ops, session_id=session_id, workflow_id=workflow_id
        )
    else:
        confirmed_nodes, confirmed_edges = await _run_legacy_ops(
            ops, session_id=session_id, workflow_id=workflow_id
        )

    # --- Signal ready ---
    async with async_session_factory() as db:
        await definition_event_service.publish(
            db,
            workflow_id=workflow_id,
            event_type="build_ready",
            payload={"session_id": str(session_id)},
        )

    logger.info(
        "agent.build_workflow.ready",
        session_id=str(session_id),
        nodes=confirmed_nodes,
        edges=confirmed_edges,
        thread_id=thread_id,
    )

    # --- Pause and wait for user decision ---
    decision = interrupt(
        {
            "type": "build_ready",
            "session_id": str(session_id),
            "workflow_id": str(workflow_id),
            "pending_nodes": confirmed_nodes,
            "pending_edges": confirmed_edges,
            "plan_summary": summary,
        }
    )

    action = (decision or {}).get("action", "cancel") if isinstance(decision, dict) else "cancel"

    duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    total_tokens = sum(
        t.get("total_tokens", 0)
        for t in (state.get("token_usage") or [])
    )

    if action == "confirm":
        try:
            async with async_session_factory() as db:
                confirm_result = await build_session_service.confirm(session_id, db)
            await build_session_service.set_audit(
                session_id,
                {"confirmed_at": datetime.now(timezone.utc).isoformat()},
            )
            logger.info(
                "agent.build_workflow.confirmed",
                session_id=str(session_id),
                nodes_added=confirm_result.nodes_added,
                edges_added=confirm_result.edges_added,
            )
            await _write_audit(
                thread_id=thread_id,
                user_id=str(user_id_raw) if user_id_raw else None,
                session_id=str(session_id),
                workflow_id=str(workflow_id),
                build_plan=build_plan,
                operations_applied=[],
                status="confirmed",
                total_tokens=total_tokens,
                duration_ms=duration_ms,
                user_prompt=user_prompt,
            )
            report = (
                f"\u2713 {confirm_result.nodes_added} no(s) e "
                f"{confirm_result.edges_added} aresta(s) "
                f"adicionados ao workflow com sucesso.\n\n{summary}"
            )
        except BuildSessionNotFoundError:
            logger.warning("agent.build_workflow.session_expired_on_confirm", session_id=str(session_id))
            report = (
                "A sessao de build expirou antes de ser confirmada. "
                "Inicie uma nova conversa para tentar novamente."
            )
        except Exception as exc:
            logger.exception("agent.build_workflow.confirm_failed", session_id=str(session_id))
            await _write_audit(
                thread_id=thread_id,
                user_id=str(user_id_raw) if user_id_raw else None,
                session_id=str(session_id),
                workflow_id=str(workflow_id),
                build_plan=build_plan,
                operations_applied=[],
                status="confirm_failed",
                total_tokens=total_tokens,
                duration_ms=duration_ms,
                user_prompt=user_prompt,
            )
            report = (
                "Falha ao aplicar as mudancas no workflow. "
                "Nenhuma alteracao foi persistida. "
                f"Detalhe: {exc}"
            )
    else:
        await build_session_service.cancel(session_id)
        await build_session_service.set_audit(
            session_id,
            {"cancelled_at": datetime.now(timezone.utc).isoformat()},
        )
        async with async_session_factory() as db:
            await definition_event_service.publish(
                db,
                workflow_id=workflow_id,
                event_type="build_cancelled",
                payload={"session_id": str(session_id)},
            )
        await _write_audit(
            thread_id=thread_id,
            user_id=str(user_id_raw) if user_id_raw else None,
            session_id=str(session_id),
            workflow_id=str(workflow_id),
            build_plan=build_plan,
            operations_applied=[],
            status="cancelled",
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            user_prompt=user_prompt,
        )
        logger.info("agent.build_workflow.cancelled", session_id=str(session_id))
        report = "Construcao cancelada. Nenhuma alteracao foi feita no workflow."

    return {
        "build_session_id": str(session_id),
        "final_report": report,
    }
