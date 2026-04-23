"""
Servico de build sessions para o modo de construcao do Platform Agent.

Uma build session representa uma sessao em que a IA esta propondo mudancas
em um workflow antes de o usuario confirmar. As operacoes pendentes sao
armazenadas em memoria com TTL de 30 minutos.

Ciclo de vida:
  1. POST .../build-sessions           -> create()  -> emite build_started
  2. POST .../pending-nodes            -> add_pending_node() -> emite pending_node_added
  3. POST .../pending-edges            -> add_pending_edge() -> emite pending_edge_added
  4. PUT  .../pending-nodes/{node_id}  -> update_pending_node() -> emite pending_node_updated
  5. DELETE .../pending-nodes/{id}     -> remove_pending_node() -> emite pending_node_removed
  6. POST .../ready                    -> (sem mutacao, emite build_ready)
  7. POST .../confirm                  -> confirm() -> aplica ops, emite node_added/edge_added
  8. POST .../cancel                   -> cancel()  -> emite build_cancelled
"""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# TTL longo em vez de heartbeat — simplicidade sobre precisão.
# O build node não envia heartbeats; sessões expiram naturalmente após 30min.
_SESSION_TTL_SECONDS = 30 * 60       # 30 minutos
_BUILD_SESSIONS_PER_USER_PER_DAY = 50  # Budget: max build sessions por usuario/dia
_MAX_OPS_PER_SESSION = 50            # Limite de operacoes (nos) por sessao

# Idempotency cache for confirm — replace with Redis in multi-replica deployments.
# Key: "confirm_idem:{session_id}:{idempotency_key}" → (ConfirmResult, expires_monotonic)
_confirm_idem_cache: dict[str, tuple["ConfirmResult", float]] = {}
_CONFIRM_IDEM_TTL = 24 * 3600  # seconds


# ---------------------------------------------------------------------------
# Modelos de dados (imutaveis por convencao apos criacao)
# ---------------------------------------------------------------------------


@dataclass
class PendingNode:
    node_id: str
    node_type: str
    position: dict[str, Any]
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "type": self.node_type,
            "position": self.position,
            "data": {**self.data, "__pending": True},
        }


@dataclass
class PendingEdge:
    edge_id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "__pending": True,
        }
        if self.source_handle is not None:
            d["sourceHandle"] = self.source_handle
        if self.target_handle is not None:
            d["targetHandle"] = self.target_handle
        return d


@dataclass
class ConfirmResult:
    """Resultado de uma confirmação de build session."""
    nodes_added: int
    edges_added: int
    session_id: uuid.UUID


class BuildSessionNotFoundError(Exception):
    """Sessão não encontrada, expirada ou já finalizada."""


@dataclass
class BuildSession:
    session_id: uuid.UUID
    workflow_id: uuid.UUID
    created_at: datetime
    pending_nodes: dict[str, PendingNode] = field(default_factory=dict)
    pending_edges: dict[str, PendingEdge] = field(default_factory=dict)
    confirmed: bool = False
    cancelled: bool = False
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Audit data — preenchido ao longo do ciclo de vida da sessao
    audit: dict[str, Any] = field(default_factory=dict)
    # temp_id → node_id: mapeamento para resolucao de referencias no plano LLM
    temp_id_map: dict[str, str] = field(default_factory=dict)
    # Variaveis pendentes a aplicar no confirm()
    variables: list[dict[str, Any]] = field(default_factory=list)
    # Schema de I/O (inputs/outputs) do subfluxo, a aplicar no confirm()
    io_schema: dict[str, Any] | None = None

    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return elapsed > _SESSION_TTL_SECONDS

    def is_active(self) -> bool:
        return not self.confirmed and not self.cancelled and not self.is_expired()


# ---------------------------------------------------------------------------
# Servico
# ---------------------------------------------------------------------------


class BuildSessionService:
    """Armazena build sessions em memoria com asyncio.Lock para thread-safety."""

    def __init__(self) -> None:
        self._sessions: dict[str, BuildSession] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        # Budget: {user_id_str -> [(datetime, session_id)]} — sliding window diaria
        self._user_session_log: dict[str, list[datetime]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Ciclo de vida da sessao
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Budget helpers
    # ------------------------------------------------------------------

    def _sessions_today(self, user_id: str) -> int:
        """Conta sessoes criadas pelo usuario nas ultimas 24h (janela deslizante)."""
        cutoff = datetime.now(timezone.utc).timestamp() - 86_400
        timestamps = self._user_session_log.get(user_id, [])
        recent = [t for t in timestamps if t.timestamp() > cutoff]
        self._user_session_log[user_id] = recent
        return len(recent)

    def check_build_budget(self, user_id: str) -> tuple[bool, str | None]:
        """Retorna (ok, motivo). Nao precisa de lock (leitura aproximada e suficiente)."""
        count = self._sessions_today(user_id)
        if count >= _BUILD_SESSIONS_PER_USER_PER_DAY:
            return (
                False,
                f"Limite de {_BUILD_SESSIONS_PER_USER_PER_DAY} build sessions/dia atingido "
                f"({count} usadas). Tente novamente amanha.",
            )
        return True, None

    # ------------------------------------------------------------------
    # Ciclo de vida da sessao
    # ------------------------------------------------------------------

    async def create(
        self, workflow_id: uuid.UUID, user_id: str | None = None
    ) -> BuildSession:
        """Cria uma nova build session para o workflow."""
        async with self._lock:
            session = BuildSession(
                session_id=uuid.uuid4(),
                workflow_id=workflow_id,
                created_at=datetime.now(timezone.utc),
            )
            self._sessions[str(session.session_id)] = session
            if user_id:
                self._user_session_log[user_id].append(session.created_at)
            return session

    async def get(self, session_id: uuid.UUID) -> BuildSession | None:
        """Retorna a sessao se existir, nao expirada."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return None
            if session.is_expired():
                del self._sessions[str(session_id)]
                return None
            return session

    async def confirm(
        self,
        session_id: uuid.UUID,
        db: Any,  # AsyncSession — typed as Any to avoid top-level SQLAlchemy import
        *,
        idempotency_key: str | None = None,
        client_mutation_id: str | None = None,
    ) -> ConfirmResult:
        """Confirma a sessão: persiste nós/arestas no banco atomicamente.

        Levanta BuildSessionNotFoundError se a sessão não existe, expirou ou foi cancelada.
        Em caso de falha de BD, faz rollback, publica build_failed em transação nova e
        re-levanta a exceção para o chamador registrar o erro.
        """
        from sqlalchemy import select as _select
        from app.models.workflow import Workflow as _Workflow
        from app.services.definition_event_service import definition_event_service as _des

        # Idempotency-Key: retorna resultado cacheado se já processado
        idem_cache_key: str | None = None
        if idempotency_key:
            idem_cache_key = f"confirm_idem:{session_id}:{idempotency_key}"
            cached = _confirm_idem_cache.get(idem_cache_key)
            if cached is not None:
                result, expires_at = cached
                if time.monotonic() < expires_at:
                    return result
                del _confirm_idem_cache[idem_cache_key]

        # Snapshot pending state under lock; validate session
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or session.is_expired():
                raise BuildSessionNotFoundError(
                    f"Build session '{session_id}' nao encontrada ou expirada."
                )
            if session.cancelled:
                raise BuildSessionNotFoundError(
                    f"Build session '{session_id}' foi cancelada."
                )
            workflow_id = session.workflow_id
            pending_nodes = dict(session.pending_nodes)
            pending_edges = dict(session.pending_edges)
            pending_variables = list(session.variables)
            pending_io_schema = (
                copy.deepcopy(session.io_schema) if session.io_schema else None
            )

        # DB work outside lock
        stmt = _select(_Workflow).where(_Workflow.id == workflow_id).with_for_update()
        wf = (await db.execute(stmt)).scalar_one_or_none()
        if wf is None:
            raise BuildSessionNotFoundError(f"Workflow '{workflow_id}' nao encontrado.")

        definition = copy.deepcopy(wf.definition) if isinstance(wf.definition, dict) else {}
        nodes_list: list[dict[str, Any]] = list(definition.get("nodes") or [])
        edges_list: list[dict[str, Any]] = list(definition.get("edges") or [])

        existing_node_ids = {n["id"] for n in nodes_list}
        existing_edge_ids = {e["id"] for e in edges_list}

        added_nodes: list[dict[str, Any]] = []
        added_edges: list[dict[str, Any]] = []

        for node in pending_nodes.values():
            if node.node_id in existing_node_ids:
                continue
            node_dict: dict[str, Any] = {
                "id": node.node_id,
                "type": node.node_type,
                "position": node.position,
                "data": {k: v for k, v in node.data.items() if k != "__pending"},
            }
            nodes_list.append(node_dict)
            added_nodes.append(node_dict)

        for edge in pending_edges.values():
            if edge.edge_id in existing_edge_ids:
                continue
            edge_dict: dict[str, Any] = {
                "id": edge.edge_id,
                "source": edge.source,
                "target": edge.target,
            }
            if edge.source_handle is not None:
                edge_dict["sourceHandle"] = edge.source_handle
            if edge.target_handle is not None:
                edge_dict["targetHandle"] = edge.target_handle
            edges_list.append(edge_dict)
            added_edges.append(edge_dict)

        definition["nodes"] = nodes_list
        definition["edges"] = edges_list
        if pending_variables:
            definition["variables"] = pending_variables
        if pending_io_schema is not None:
            # Merge: preserva inputs/outputs existentes se a sessao so setou um lado.
            existing_io = definition.get("io_schema") or {}
            merged_io = {
                "inputs": pending_io_schema.get("inputs")
                if pending_io_schema.get("inputs") is not None
                else existing_io.get("inputs", []),
                "outputs": pending_io_schema.get("outputs")
                if pending_io_schema.get("outputs") is not None
                else existing_io.get("outputs", []),
            }
            definition["io_schema"] = merged_io
        wf.definition = definition

        try:
            await db.flush()

            for node_dict in added_nodes:
                await _des.publish_within_tx(
                    db,
                    workflow_id=workflow_id,
                    event_type="node_added",
                    payload={
                        "node_id": node_dict["id"],
                        "node_type": node_dict["type"],
                        "position": node_dict["position"],
                        "data": node_dict["data"],
                    },
                    client_mutation_id=client_mutation_id,
                )

            for edge_dict in added_edges:
                ep: dict[str, Any] = {
                    "edge_id": edge_dict["id"],
                    "source": edge_dict["source"],
                    "target": edge_dict["target"],
                }
                if "sourceHandle" in edge_dict:
                    ep["sourceHandle"] = edge_dict["sourceHandle"]
                if "targetHandle" in edge_dict:
                    ep["targetHandle"] = edge_dict["targetHandle"]
                await _des.publish_within_tx(
                    db,
                    workflow_id=workflow_id,
                    event_type="edge_added",
                    payload=ep,
                    client_mutation_id=client_mutation_id,
                )

            await _des.publish_within_tx(
                db,
                workflow_id=workflow_id,
                event_type="build_confirmed",
                payload={
                    "session_id": str(session_id),
                    "nodes_added": len(added_nodes),
                    "edges_added": len(added_edges),
                },
            )
            await db.commit()

        except Exception as exc:
            await db.rollback()
            # Publish build_failed in a fresh transaction (current one is rolled back)
            try:
                from app.db.session import async_session_factory as _factory
                async with _factory() as fail_db:
                    await _des.publish(
                        fail_db,
                        workflow_id=workflow_id,
                        event_type="build_failed",
                        payload={"session_id": str(session_id), "reason": str(exc)},
                    )
            except Exception:
                pass  # build_failed is best-effort; primary error takes precedence
            raise

        # Mark confirmed in-memory after successful commit
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is not None:
                session.confirmed = True

        result = ConfirmResult(
            nodes_added=len(added_nodes),
            edges_added=len(added_edges),
            session_id=session_id,
        )
        if idem_cache_key:
            _confirm_idem_cache[idem_cache_key] = (result, time.monotonic() + _CONFIRM_IDEM_TTL)
        return result

    async def cancel(self, session_id: uuid.UUID) -> BuildSession | None:
        """Cancela a sessao e remove da memoria."""
        async with self._lock:
            session = self._sessions.pop(str(session_id), None)
            if session is None:
                return None
            session.cancelled = True
            return session

    # ------------------------------------------------------------------
    # Operacoes sobre nos pendentes
    # ------------------------------------------------------------------

    async def add_pending_node(
        self,
        session_id: uuid.UUID,
        *,
        node_type: str,
        position: dict[str, Any],
        data: dict[str, Any],
        temp_id: str | None = None,
    ) -> PendingNode | None:
        """Adiciona um no pendente. Retorna None se sessao inativa ou temp_id duplicado."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return None
            if temp_id and temp_id in session.temp_id_map:
                return None  # duplicate temp_id rejected
            node_id = f"node_{uuid.uuid4().hex[:12]}"
            node = PendingNode(
                node_id=node_id,
                node_type=node_type,
                position=position,
                data=data,
            )
            session.pending_nodes[node_id] = node
            if temp_id:
                session.temp_id_map[temp_id] = node_id
            return node

    async def update_pending_node(
        self,
        session_id: uuid.UUID,
        node_id: str,
        data_patch: dict[str, Any],
    ) -> PendingNode | None:
        """Merge shallow do data_patch no no pendente existente."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return None
            node = session.pending_nodes.get(node_id)
            if node is None:
                return None
            node.data = {**node.data, **data_patch}
            return node

    async def remove_pending_node(
        self,
        session_id: uuid.UUID,
        node_id: str,
    ) -> PendingNode | None:
        """Remove no pendente e arestas pendentes conectadas a ele."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return None
            node = session.pending_nodes.pop(node_id, None)
            if node is None:
                return None
            # Remove arestas pendentes que referenciam este no
            orphaned = [
                eid
                for eid, e in session.pending_edges.items()
                if e.source == node_id or e.target == node_id
            ]
            for eid in orphaned:
                del session.pending_edges[eid]
            return node

    # ------------------------------------------------------------------
    # Operacoes sobre arestas pendentes
    # ------------------------------------------------------------------

    async def add_pending_edge(
        self,
        session_id: uuid.UUID,
        *,
        source: str,
        target: str,
        source_handle: str | None = None,
        target_handle: str | None = None,
    ) -> PendingEdge | None:
        """Adiciona uma aresta pendente."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return None
            edge_id = f"edge_{uuid.uuid4().hex[:12]}"
            edge = PendingEdge(
                edge_id=edge_id,
                source=source,
                target=target,
                source_handle=source_handle,
                target_handle=target_handle,
            )
            session.pending_edges[edge_id] = edge
            return edge

    async def remove_pending_edge(
        self,
        session_id: uuid.UUID,
        edge_id: str,
    ) -> PendingEdge | None:
        """Remove uma aresta pendente."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return None
            return session.pending_edges.pop(edge_id, None)

    # ------------------------------------------------------------------
    # TempId helpers (FASE 5)
    # ------------------------------------------------------------------

    async def get_node_id_for_temp_id(
        self, session_id: uuid.UUID, temp_id: str
    ) -> str | None:
        """Resolve temp_id para o node_id real. Retorna None se nao mapeado."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return None
            return session.temp_id_map.get(temp_id)

    async def has_temp_id(self, session_id: uuid.UUID, temp_id: str) -> bool:
        """Retorna True se temp_id ja foi registrado nesta sessao."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return False
            return temp_id in session.temp_id_map

    async def set_variables(
        self, session_id: uuid.UUID, variables: list[dict[str, Any]]
    ) -> bool:
        """Define variaveis pendentes para aplicar no confirm. Retorna False se inativa."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return False
            session.variables = list(variables)
            return True

    async def set_io_schema(
        self, session_id: uuid.UUID, io_schema: dict[str, Any]
    ) -> bool:
        """Define o schema de I/O pendente (inputs/outputs) do subfluxo.

        Aplicado em definition.io_schema no confirm().
        Retorna False se a sessao nao estiver ativa.
        """
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return False
            session.io_schema = {
                "inputs": list(io_schema.get("inputs") or []),
                "outputs": list(io_schema.get("outputs") or []),
            }
            return True

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def renew_heartbeat(self, session_id: uuid.UUID) -> bool:
        """Atualiza last_heartbeat. Retorna False se sessao nao encontrada/inativa."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or not session.is_active():
                return False
            session.last_heartbeat = datetime.now(timezone.utc)
            return True

    # ------------------------------------------------------------------
    # Audit data
    # ------------------------------------------------------------------

    async def set_audit(self, session_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Persiste dados de auditoria na sessao (merge shallow)."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is not None:
                session.audit = {**session.audit, **data}

    async def get_audit(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        """Retorna dados de auditoria da sessao, ou None se nao encontrada."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            return dict(session.audit) if session else None

    # ------------------------------------------------------------------
    # Manutencao
    # ------------------------------------------------------------------

    async def cleanup_expired(self) -> int:
        """Remove sessoes expiradas (TTL 30min). Retorna quantas foram removidas."""
        async with self._lock:
            to_remove = [k for k, v in self._sessions.items() if v.is_expired()]
            for k in to_remove:
                del self._sessions[k]
            return len(to_remove)

    async def count(self) -> int:
        async with self._lock:
            return len(self._sessions)

    async def pending_node_count(self, session_id: uuid.UUID) -> int | None:
        """Retorna quantos nos pendentes existem na sessao, ou None se nao encontrada."""
        async with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None:
                return None
            return len(session.pending_nodes)


build_session_service = BuildSessionService()
