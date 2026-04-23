"""
Endpoints para Build Sessions — modo de construcao do Platform Agent.

Permite que a IA proponha mudancas (nos/arestas pendentes) antes de o
usuario confirmar. Tudo e armazenado em memoria com TTL de 30 minutos.

Fluxo tipico:
  POST   /workflows/{id}/build-sessions                          -> cria sessao
  POST   /workflows/{id}/build-sessions/{sid}/pending-nodes      -> adiciona no fantasma
  PUT    /workflows/{id}/build-sessions/{sid}/pending-nodes/{nid}-> atualiza no fantasma
  DELETE /workflows/{id}/build-sessions/{sid}/pending-nodes/{nid}-> remove no fantasma
  POST   /workflows/{id}/build-sessions/{sid}/pending-edges      -> adiciona aresta fantasma
  DELETE /workflows/{id}/build-sessions/{sid}/pending-edges/{eid}-> remove aresta fantasma
  POST   /workflows/{id}/build-sessions/{sid}/ready              -> IA terminou de propor
  POST   /workflows/{id}/build-sessions/{sid}/confirm            -> aplica tudo no banco
  POST   /workflows/{id}/build-sessions/{sid}/cancel             -> descarta tudo
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import require_permission
from app.models.workflow import Workflow
from app.models.workflow_definition_event import WorkflowDefinitionEvent
from app.services.build_session_service import (
    BuildSessionNotFoundError,
    ConfirmResult,
    _confirm_idem_cache,
    build_session_service,
)
from app.services.definition_event_service import definition_event_service

logger = get_logger(__name__)

router = APIRouter(tags=["workflow-build"])


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------


class CreateBuildSessionRequest(BaseModel):
    reason: str = Field(default="", description="Descricao da intencao da sessao")


class CreateBuildSessionResponse(BaseModel):
    session_id: str
    workflow_id: str


class AddPendingNodeRequest(BaseModel):
    node_type: str
    position: dict[str, Any]
    data: dict[str, Any] = Field(default_factory=dict)


class AddPendingNodeResponse(BaseModel):
    node_id: str
    node: dict[str, Any]


class UpdatePendingNodeRequest(BaseModel):
    data_patch: dict[str, Any]


class AddPendingEdgeRequest(BaseModel):
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class AddPendingEdgeResponse(BaseModel):
    edge_id: str
    edge: dict[str, Any]


class ConfirmBuildResponse(BaseModel):
    nodes_added: int
    edges_added: int


# ---------------------------------------------------------------------------
# Helper: carrega workflow verificando escopo
# ---------------------------------------------------------------------------


async def _get_workflow_or_404(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow:
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )
    return wf


async def _get_session_or_404(session_id: uuid.UUID):
    session = await build_session_service.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build session '{session_id}' nao encontrada ou expirada.",
        )
    return session


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/build-sessions",
    response_model=CreateBuildSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_build_session(
    workflow_id: uuid.UUID,
    body: CreateBuildSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("workspace", "CONSULTANT")),
) -> CreateBuildSessionResponse:
    """Inicia uma build session. Emite build_started no canal SSE do workflow."""
    ok, reason = build_session_service.check_build_budget(str(current_user.id))
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "build_budget_exceeded", "message": reason},
        )
    await _get_workflow_or_404(db, workflow_id)
    session = await build_session_service.create(workflow_id, user_id=str(current_user.id))

    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="build_started",
        payload={
            "session_id": str(session.session_id),
            "reason": body.reason,
        },
    )

    return CreateBuildSessionResponse(
        session_id=str(session.session_id),
        workflow_id=str(workflow_id),
    )


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/pending-nodes",
    response_model=AddPendingNodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_pending_node(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    body: AddPendingNodeRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> AddPendingNodeResponse:
    """Adiciona um no fantasma a sessao. Emite pending_node_added no SSE."""
    build_session = await _get_session_or_404(session_id)
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Session nao pertence a este workflow.",
        )

    node = await build_session_service.add_pending_node(
        session_id,
        node_type=body.node_type,
        position=body.position,
        data=body.data,
    )
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session expirada ou ja finalizada.",
        )

    node_dict = node.to_dict()
    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="pending_node_added",
        payload={"node": node_dict},
    )

    return AddPendingNodeResponse(node_id=node.node_id, node=node_dict)


@router.put(
    "/workflows/{workflow_id}/build-sessions/{session_id}/pending-nodes/{node_id}",
    status_code=status.HTTP_200_OK,
)
async def update_pending_node(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    node_id: str,
    body: UpdatePendingNodeRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Atualiza (merge shallow) o data de um no fantasma. Emite pending_node_updated."""
    build_session = await _get_session_or_404(session_id)
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=422, detail="Session nao pertence a este workflow.")

    node = await build_session_service.update_pending_node(session_id, node_id, body.data_patch)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pendente '{node_id}' nao encontrado.",
        )

    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="pending_node_updated",
        payload={"node_id": node_id, "data_patch": body.data_patch},
    )

    return {"node_id": node_id, "node": node.to_dict()}


@router.delete(
    "/workflows/{workflow_id}/build-sessions/{session_id}/pending-nodes/{node_id}",
    status_code=status.HTTP_200_OK,
)
async def remove_pending_node(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    node_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Remove um no fantasma (e arestas orphas). Emite pending_node_removed."""
    build_session = await _get_session_or_404(session_id)
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=422, detail="Session nao pertence a este workflow.")

    node = await build_session_service.remove_pending_node(session_id, node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pendente '{node_id}' nao encontrado.",
        )

    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="pending_node_removed",
        payload={"node_id": node_id},
    )

    return {"node_id": node_id}


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/pending-edges",
    response_model=AddPendingEdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_pending_edge(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    body: AddPendingEdgeRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> AddPendingEdgeResponse:
    """Adiciona uma aresta fantasma. Emite pending_edge_added no SSE."""
    build_session = await _get_session_or_404(session_id)
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=422, detail="Session nao pertence a este workflow.")

    edge = await build_session_service.add_pending_edge(
        session_id,
        source=body.source,
        target=body.target,
        source_handle=body.source_handle,
        target_handle=body.target_handle,
    )
    if edge is None:
        raise HTTPException(status_code=409, detail="Session expirada ou ja finalizada.")

    edge_dict = edge.to_dict()
    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="pending_edge_added",
        payload={"edge": edge_dict},
    )

    return AddPendingEdgeResponse(edge_id=edge.edge_id, edge=edge_dict)


@router.delete(
    "/workflows/{workflow_id}/build-sessions/{session_id}/pending-edges/{edge_id}",
    status_code=status.HTTP_200_OK,
)
async def remove_pending_edge(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    edge_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Remove uma aresta fantasma. Emite pending_edge_removed no SSE."""
    build_session = await _get_session_or_404(session_id)
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=422, detail="Session nao pertence a este workflow.")

    edge = await build_session_service.remove_pending_edge(session_id, edge_id)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aresta pendente '{edge_id}' nao encontrada.",
        )

    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="pending_edge_removed",
        payload={"edge_id": edge_id},
    )

    return {"edge_id": edge_id}


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/ready",
    status_code=status.HTTP_200_OK,
)
async def mark_build_ready(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """IA terminou de propor mudancas. Emite build_ready para o frontend mostrar botoes."""
    build_session = await _get_session_or_404(session_id)
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=422, detail="Session nao pertence a este workflow.")

    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="build_ready",
        payload={
            "session_id": str(session_id),
            "pending_nodes": len(build_session.pending_nodes),
            "pending_edges": len(build_session.pending_edges),
        },
    )

    return {
        "session_id": str(session_id),
        "pending_nodes": len(build_session.pending_nodes),
        "pending_edges": len(build_session.pending_edges),
    }


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/confirm",
    response_model=ConfirmBuildResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_build_session(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_client_mutation_id: str | None = Header(None, alias="X-Client-Mutation-Id"),
) -> ConfirmBuildResponse:
    """
    Confirma a build session: persiste todos os nos/arestas pendentes no banco
    em uma unica transacao atomica (mutacao + eventos + pg_notify), encerra a sessao.

    Thin wrapper — toda a logica de persistencia vive em build_session_service.confirm().
    Suporta Idempotency-Key (TTL 24h).
    """
    try:
        result: ConfirmResult = await build_session_service.confirm(
            session_id,
            db,
            idempotency_key=idempotency_key,
            client_mutation_id=x_client_mutation_id,
        )
    except BuildSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("build.confirm_endpoint_error", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao confirmar build session: {exc}",
        ) from exc

    return ConfirmBuildResponse(nodes_added=result.nodes_added, edges_added=result.edges_added)


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/cancel",
    status_code=status.HTTP_200_OK,
)
async def cancel_build_session(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Cancela a sessao de build. Emite build_cancelled no SSE."""
    build_session = await build_session_service.cancel(session_id)
    if build_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build session '{session_id}' nao encontrada.",
        )

    await definition_event_service.publish(
        db,
        workflow_id=workflow_id,
        event_type="build_cancelled",
        payload={"session_id": str(session_id)},
    )

    return {"session_id": str(session_id), "cancelled": True}


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/heartbeat",
    status_code=status.HTTP_200_OK,
)
async def build_session_heartbeat(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Renova o heartbeat da sessao de build.

    O agente deve chamar este endpoint a cada ~10s durante a construcao.
    Sessoes sem heartbeat por 90s sao consideradas orfas e removidas pelo cleanup.
    """
    ok = await build_session_service.renew_heartbeat(session_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build session '{session_id}' nao encontrada ou inativa.",
        )
    return {"session_id": str(session_id), "ok": True}


class UndoBuildRequest(BaseModel):
    session_id: str = Field(description="ID da build session que foi confirmada")


@router.post(
    "/workflows/{workflow_id}/build-sessions/{session_id}/undo",
    status_code=status.HTTP_200_OK,
)
async def undo_build_session(
    workflow_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Desfaz uma build session confirmada.

    Gera operacoes inversas (remove_node para cada add_node confirmado)
    em uma unica transacao. Publica node_removed/edge_removed no SSE.
    Disponivel ate 5 minutos apos confirmacao (sessao ainda na memoria com flag confirmed).
    """
    build_session = await build_session_service.get(session_id)
    if build_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build session '{session_id}' nao encontrada (expirou ou nao existe).",
        )
    if str(build_session.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=422, detail="Session nao pertence a este workflow.")
    if not build_session.confirmed:
        raise HTTPException(status_code=409, detail="Session ainda nao foi confirmada.")

    # Carrega workflow com FOR UPDATE
    stmt = select(Workflow).where(Workflow.id == workflow_id).with_for_update()
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow nao encontrado.")

    definition = copy.deepcopy(wf.definition) if isinstance(wf.definition, dict) else {}
    session_node_ids = {n.node_id for n in build_session.pending_nodes.values()}
    session_edge_ids = {e.edge_id for e in build_session.pending_edges.values()}

    nodes_before: list[dict[str, Any]] = list(definition.get("nodes") or [])
    edges_before: list[dict[str, Any]] = list(definition.get("edges") or [])

    removed_nodes = [n for n in nodes_before if n["id"] in session_node_ids]
    removed_edges = [e for e in edges_before if e["id"] in session_edge_ids]
    # Also remove edges connected to removed nodes (orphans)
    removed_node_ids = {n["id"] for n in removed_nodes}
    orphan_edges = [
        e for e in edges_before
        if e["id"] not in session_edge_ids
        and (e.get("source") in removed_node_ids or e.get("target") in removed_node_ids)
    ]
    all_removed_edge_ids = session_edge_ids | {e["id"] for e in orphan_edges}

    definition["nodes"] = [n for n in nodes_before if n["id"] not in removed_node_ids]
    definition["edges"] = [e for e in edges_before if e["id"] not in all_removed_edge_ids]
    wf.definition = definition

    # Publica todos os eventos na mesma transacao. Captura as instancias do INSERT
    # para usar nos pg_notify — evita o race de um SELECT ORDER BY seq DESC pegar
    # eventos de transacoes concorrentes inseridos entre o flush e a query.
    import json as _json
    from datetime import datetime, timezone

    added_events: list[WorkflowDefinitionEvent] = []

    for edge in list(removed_edges) + list(orphan_edges):
        ev = WorkflowDefinitionEvent(
            workflow_id=workflow_id,
            event_type="edge_removed",
            payload={"edge_id": edge["id"], "source": edge.get("source"), "target": edge.get("target")},
        )
        db.add(ev)
        added_events.append(ev)

    for node in removed_nodes:
        ev = WorkflowDefinitionEvent(
            workflow_id=workflow_id,
            event_type="node_removed",
            payload={"node_id": node["id"], "removed_edges": list(all_removed_edge_ids)},
        )
        db.add(ev)
        added_events.append(ev)

    await db.flush()  # popula seq e id nas instancias acima

    channel = f"wfdef_{workflow_id.hex}"
    for row in added_events:  # itera sobre instancias do INSERT, nao re-query
        notify_payload = _json.dumps({
            "seq": row.seq,
            "event_id": str(row.id),
            "workflow_id": str(row.workflow_id),
            "event_type": row.event_type,
            "payload": row.payload,
            "client_mutation_id": None,
            "ts": row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat(),
        })
        await db.execute(text("SELECT pg_notify(:ch, :pl)"), {"ch": channel, "pl": notify_payload})

    await db.commit()

    logger.info(
        "build.undo",
        session_id=str(session_id),
        workflow_id=str(workflow_id),
        nodes_removed=len(removed_nodes),
        edges_removed=len(removed_edges) + len(orphan_edges),
    )

    return {
        "session_id": str(session_id),
        "nodes_removed": len(removed_nodes),
        "edges_removed": len(removed_edges) + len(orphan_edges),
    }
