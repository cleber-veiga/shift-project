"""
Tools de build pendente para o Platform Agent — FASE 5.

Operam sobre BuildSession em memoria e publicam eventos SSE sem commitar ao banco.
O commit ocorre apenas quando build_session_service.confirm() e chamado.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.build_session_service import _MAX_OPS_PER_SESSION, build_session_service
from app.services.definition_event_service import definition_event_service

logger = get_logger(__name__)


def _err(code: str, message: str, details: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return json.dumps(payload)


async def pending_add_node(
    *,
    db: Any,  # nao usado — estas tools nao tocam o DB diretamente
    ctx: Any,
    session_id: str,
    temp_id: str,
    node_type: str,
    label: str,
    config: dict[str, Any] | None = None,
    position: dict[str, Any] | None = None,
) -> str:
    """Adiciona um no pendente a sessao de build."""
    sid = UUID(session_id)
    data: dict[str, Any] = {"label": label, **(config or {})}
    pos = position or {"x": 0.0, "y": 0.0}

    if await build_session_service.has_temp_id(sid, temp_id):
        return _err("DUPLICATE_TEMP_ID", f"temp_id '{temp_id}' ja usado nesta sessao.")

    current_count = await build_session_service.pending_node_count(sid)
    if current_count is not None and current_count >= _MAX_OPS_PER_SESSION:
        return _err(
            "OPS_LIMIT_EXCEEDED",
            f"Limite de {_MAX_OPS_PER_SESSION} nos por sessao atingido.",
            {"limit": _MAX_OPS_PER_SESSION, "current": current_count},
        )

    node = await build_session_service.add_pending_node(
        sid,
        node_type=node_type,
        position=pos,
        data=data,
        temp_id=temp_id,
    )
    if node is None:
        return _err("SESSION_INACTIVE", f"Sessao '{session_id}' nao encontrada ou inativa.")

    session = await build_session_service.get(sid)
    if session is not None:
        async with async_session_factory() as pub_db:
            await definition_event_service.publish(
                pub_db,
                workflow_id=session.workflow_id,
                event_type="pending_node_added",
                payload={"node": node.to_dict()},
            )

    logger.debug(
        "pending_tool.add_node",
        session_id=session_id,
        temp_id=temp_id,
        node_id=node.node_id,
    )
    return json.dumps({
        "node_id": node.node_id,
        "temp_id": temp_id,
        "node_type": node_type,
        "position": pos,
    })


async def pending_add_edge(
    *,
    db: Any,
    ctx: Any,
    session_id: str,
    source_temp_id: str,
    target_temp_id: str,
    source_handle: str | None = None,
    target_handle: str | None = None,
) -> str:
    """Conecta dois nos pendentes pelo temp_id de cada um."""
    sid = UUID(session_id)

    source_id = await build_session_service.get_node_id_for_temp_id(sid, source_temp_id)
    target_id = await build_session_service.get_node_id_for_temp_id(sid, target_temp_id)

    if source_id is None:
        return _err(
            "UNKNOWN_TEMP_ID",
            f"source_temp_id '{source_temp_id}' nao encontrado.",
            {"field": "source_temp_id"},
        )
    if target_id is None:
        return _err(
            "UNKNOWN_TEMP_ID",
            f"target_temp_id '{target_temp_id}' nao encontrado.",
            {"field": "target_temp_id"},
        )

    edge = await build_session_service.add_pending_edge(
        sid,
        source=source_id,
        target=target_id,
        source_handle=source_handle,
        target_handle=target_handle,
    )
    if edge is None:
        return _err("SESSION_INACTIVE", f"Sessao '{session_id}' nao encontrada ou inativa.")

    session = await build_session_service.get(sid)
    if session is not None:
        async with async_session_factory() as pub_db:
            await definition_event_service.publish(
                pub_db,
                workflow_id=session.workflow_id,
                event_type="pending_edge_added",
                payload={"edge": edge.to_dict()},
            )

    return json.dumps({
        "edge_id": edge.edge_id,
        "source": source_id,
        "target": target_id,
        "source_temp_id": source_temp_id,
        "target_temp_id": target_temp_id,
    })


async def pending_update_node(
    *,
    db: Any,
    ctx: Any,
    session_id: str,
    temp_id: str,
    config_patch: dict[str, Any],
) -> str:
    """Aplica patch shallow na configuracao de um no pendente."""
    sid = UUID(session_id)

    node_id = await build_session_service.get_node_id_for_temp_id(sid, temp_id)
    if node_id is None:
        return _err("UNKNOWN_TEMP_ID", f"temp_id '{temp_id}' nao encontrado.")

    node = await build_session_service.update_pending_node(sid, node_id, config_patch)
    if node is None:
        return _err("SESSION_INACTIVE", f"Sessao '{session_id}' nao encontrada ou inativa.")

    session = await build_session_service.get(sid)
    if session is not None:
        async with async_session_factory() as pub_db:
            await definition_event_service.publish(
                pub_db,
                workflow_id=session.workflow_id,
                event_type="pending_node_updated",
                payload={"node": node.to_dict()},
            )

    return json.dumps({"node_id": node_id, "temp_id": temp_id, "updated": True})


async def pending_remove_node(
    *,
    db: Any,
    ctx: Any,
    session_id: str,
    temp_id: str,
) -> str:
    """Remove um no pendente e suas arestas conectadas."""
    sid = UUID(session_id)

    node_id = await build_session_service.get_node_id_for_temp_id(sid, temp_id)
    if node_id is None:
        return _err("UNKNOWN_TEMP_ID", f"temp_id '{temp_id}' nao encontrado.")

    node = await build_session_service.remove_pending_node(sid, node_id)
    if node is None:
        return _err(
            "SESSION_INACTIVE",
            f"Sessao '{session_id}' nao encontrada ou no nao encontrado.",
        )

    session = await build_session_service.get(sid)
    if session is not None:
        async with async_session_factory() as pub_db:
            await definition_event_service.publish(
                pub_db,
                workflow_id=session.workflow_id,
                event_type="pending_node_removed",
                payload={"node_id": node_id},
            )

    return json.dumps({"node_id": node_id, "temp_id": temp_id, "removed": True})


async def pending_set_variables(
    *,
    db: Any,
    ctx: Any,
    session_id: str,
    variables: list[dict[str, Any]],
) -> str:
    """Define variaveis do workflow a serem aplicadas no confirm."""
    sid = UUID(session_id)

    ok = await build_session_service.set_variables(sid, variables)
    if not ok:
        return _err("SESSION_INACTIVE", f"Sessao '{session_id}' nao encontrada ou inativa.")

    return json.dumps({"variables_count": len(variables), "set": True})


async def pending_set_io_schema(
    *,
    db: Any,
    ctx: Any,
    session_id: str,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
) -> str:
    """Define o Schema de I/O do subfluxo (inputs/outputs) a ser aplicado no confirm.

    Necessario quando o workflow sendo construido e um subfluxo chamavel via
    call_workflow: o runtime valida inputs/outputs contra esse schema. Cada
    item de inputs/outputs segue o shape WorkflowParam:
      {"name": "ESTAB", "type": "string", "required": true, "description": "..."}
    Tipos validos: string | integer | number | boolean | object | array
                 | table_reference | connection | file_upload | secret.
    """
    sid = UUID(session_id)

    io_schema = {
        "inputs": list(inputs or []),
        "outputs": list(outputs or []),
    }
    ok = await build_session_service.set_io_schema(sid, io_schema)
    if not ok:
        return _err("SESSION_INACTIVE", f"Sessao '{session_id}' nao encontrada ou inativa.")

    return json.dumps(
        {
            "inputs_count": len(io_schema["inputs"]),
            "outputs_count": len(io_schema["outputs"]),
            "set": True,
        }
    )
