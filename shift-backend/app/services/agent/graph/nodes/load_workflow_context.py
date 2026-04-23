"""
Node: load_workflow_context

Carrega a definicao atual do workflow (nos, arestas, variaveis) antes do planner
para intencoes que editam um workflow existente (extend_workflow, edit_workflow,
create_sub_workflow).

build_workflow: pula — cria do zero, sem contexto existente relevante.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.graph.state import PlatformAgentState

logger = get_logger(__name__)

# Intencoes que precisam do contexto atual do workflow
_EXISTING_WF_INTENTS = {"extend_workflow", "edit_workflow", "create_sub_workflow"}
# Todas as intencoes de construcao tambem recebem o catalogo de conexoes
# disponivel no projeto, para que o planner possa resolver connection_id
# em nos sql_script sem alucinar UUIDs.
_BUILD_INTENTS = _EXISTING_WF_INTENTS | {"build_workflow"}

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


async def _load_project_connections(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Retorna uma lista slim de conexoes visiveis ao usuario no escopo do projeto.

    Os dados sao somente metadados nao-sensiveis (id/nome/tipo/host/banco) para
    que o planner de build possa resolver connection_id sem inventar UUID.
    """
    try:
        from app.services.connection_service import connection_service

        async with async_session_factory() as session:
            if project_id is not None:
                conns = await connection_service.list_for_project(
                    session, project_id, workspace_id, user_id
                )
            else:
                conns = await connection_service.list(session, workspace_id, user_id)
    except Exception:
        logger.exception(
            "agent.load_workflow_context.connections_error",
            project_id=str(project_id) if project_id else None,
        )
        return []

    slim: list[dict[str, Any]] = []
    for c in conns:
        slim.append(
            {
                "id": str(c.id),
                "name": c.name,
                "type": c.type,
                "host": c.host,
                "database": c.database,
            }
        )
    return slim


async def load_workflow_context_node(state: PlatformAgentState) -> dict[str, Any]:
    """Popula workflow_context para intencoes de construcao.

    Para extend/edit/create_sub_workflow: carrega definition atual (nos,
    arestas, variaveis). Para build_workflow: nao carrega workflow mas
    ainda inclui o catalogo de conexoes do projeto, para que o planner
    resolva connection_id em nos sql_script.
    """
    intent_data = state.get("current_intent") or {}
    intent = intent_data.get("intent")
    if intent not in _BUILD_INTENTS:
        return {}

    ctx = state.get("user_context") or {}
    workspace_id_raw = ctx.get("workspace_id")
    project_id_raw = ctx.get("project_id")
    user_id_raw = ctx.get("user_id")

    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    try:
        if workspace_id_raw:
            workspace_id = uuid.UUID(str(workspace_id_raw))
        if project_id_raw:
            project_id = uuid.UUID(str(project_id_raw))
        if user_id_raw:
            user_id = uuid.UUID(str(user_id_raw))
    except ValueError:
        workspace_id = None
        project_id = None
        user_id = None

    connections: list[dict[str, Any]] = []
    if workspace_id is not None and user_id is not None:
        connections = await _load_project_connections(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
        )

    # build_workflow nao tem workflow_id existente a carregar; so devolve
    # o catalogo de conexoes.
    if intent not in _EXISTING_WF_INTENTS:
        context: dict[str, Any] = {
            "workflow_id": None,
            "connections": connections,
        }
        logger.info(
            "agent.load_workflow_context.build_only",
            connections=len(connections),
            thread_id=state.get("thread_id"),
        )
        return {"workflow_context": context}

    user_text = _last_user_message(state.get("messages", []))
    match = _UUID_RE.search(user_text)
    if not match:
        logger.info(
            "agent.load_workflow_context.no_uuid",
            thread_id=state.get("thread_id"),
        )
        # Ainda assim devolvemos as conexoes para o planner poder usa-las
        # quando o usuario informar o workflow_id por outro meio.
        return {"workflow_context": {"workflow_id": None, "connections": connections}}

    workflow_id_str = match.group(0)
    try:
        from sqlalchemy import select as _select
        from app.models.workflow import Workflow as _Workflow

        async with async_session_factory() as session:
            stmt = _select(_Workflow).where(_Workflow.id == uuid.UUID(workflow_id_str))
            wf = (await session.execute(stmt)).scalar_one_or_none()

        if wf is None:
            logger.info(
                "agent.load_workflow_context.not_found",
                workflow_id=workflow_id_str,
            )
            return {"workflow_context": {"workflow_id": None, "connections": connections}}

        definition = wf.definition if isinstance(wf.definition, dict) else {}
        raw_nodes: list[dict[str, Any]] = definition.get("nodes") or []
        raw_edges: list[dict[str, Any]] = definition.get("edges") or []
        variables: list[Any] = definition.get("variables") or []
        io_schema: dict[str, Any] | None = definition.get("io_schema") or None

        context = {
            "workflow_id": workflow_id_str,
            "name": wf.name,
            "node_count": len(raw_nodes),
            "edge_count": len(raw_edges),
            "nodes": [
                {
                    "id": n.get("id"),
                    "type": n.get("type"),
                    "label": (n.get("data") or {}).get("label"),
                }
                for n in raw_nodes
                if isinstance(n, dict)
            ],
            "edges": [
                {
                    "id": e.get("id"),
                    "source": e.get("source"),
                    "target": e.get("target"),
                    "sourceHandle": e.get("sourceHandle"),
                }
                for e in raw_edges
                if isinstance(e, dict)
            ],
            "variables": variables,
            "io_schema": io_schema,
            "connections": connections,
        }
        logger.info(
            "agent.load_workflow_context.loaded",
            workflow_id=workflow_id_str,
            node_count=len(raw_nodes),
            edge_count=len(raw_edges),
            connections=len(connections),
        )
        return {"workflow_context": context}

    except Exception:
        logger.exception(
            "agent.load_workflow_context.error",
            workflow_id=workflow_id_str,
        )
        return {}
