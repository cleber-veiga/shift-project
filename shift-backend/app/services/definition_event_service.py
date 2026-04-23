"""
Servico de eventos de definition de workflow.

Responsabilidades:
  - Publicar eventos (INSERT + pg_notify) após mutações do Platform Agent.
  - Fornecer replay via query em workflow_definition_events.
  - Fornecer gerador SSE assíncrono para o endpoint GET .../definition/events.

Canal PostgreSQL: wfdef_{workflow_id.hex}
  — Identificador válido (alphanumeric+_), sem aspas necessárias.
  — pg_notify envia o evento completo como JSON para economizar round-trips.
  — Payload limitado a 8 KB pelo PostgreSQL (suficiente para eventos típicos).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import asyncpg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.workflow_definition_event import WorkflowDefinitionEvent

logger = get_logger(__name__)

_KEEPALIVE_INTERVAL = 20  # segundos
_MAX_REPLAY_ROWS = 500
_GRACE_SECONDS = 30  # segundos antes de fechar conexao apos ultimo subscriber
_OVERFLOW_SENTINEL = "__stream_overflow__"

# Global pool: um SharedListener por canal (workflow).
_listeners: dict[str, "SharedListener"] = {}


def _channel(workflow_id: UUID) -> str:
    """Nome do canal pg_notify: wfdef_<uuid-hex-sem-tracos>."""
    return f"wfdef_{workflow_id.hex}"


def _asyncpg_dsn() -> str:
    """Converte a URL SQLAlchemy (qualquer driver) para DSN puro asyncpg."""
    url = settings.DATABASE_URL
    parsed = urlparse(url)
    # Normalise scheme: strip driver suffix (e.g. +asyncpg, +psycopg)
    scheme = parsed.scheme.split("+")[0]
    # asyncpg only accepts 'postgresql://' not 'postgres://'
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql"
    fixed = parsed._replace(scheme=scheme)
    return urlunparse(fixed)


class SharedListener:
    """Mantém uma única conexão asyncpg com LISTEN para um canal,
    multiplexando notificações para N filas de subscribers."""

    def __init__(self, channel: str) -> None:
        self._channel = channel
        self._conn: asyncpg.Connection | None = None
        self._subs: dict[int, asyncio.Queue[str]] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._grace_task: asyncio.Task | None = None
        self._connect_task: asyncio.Task | None = asyncio.create_task(self._connect())

    def _broadcast(self, payload: str) -> None:
        for q in self._subs.values():
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Subscriber lento: enfileira sentinel para forcar reconexao do cliente.
                try:
                    q.put_nowait(_OVERFLOW_SENTINEL)
                except asyncio.QueueFull:
                    pass

    async def _connect(self) -> None:
        try:
            conn = await asyncpg.connect(_asyncpg_dsn())
            await conn.add_listener(
                self._channel,
                lambda _c, _pid, _ch, payload: self._broadcast(payload),
            )
            async with self._lock:
                self._conn = conn
            logger.debug("shared_listener.connected", channel=self._channel)
        except Exception:
            logger.exception("shared_listener.connect_failed", channel=self._channel)

    async def subscribe(self) -> tuple[int, asyncio.Queue[str]]:
        async with self._lock:
            sub_id = self._next_id
            self._next_id += 1
            q: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
            self._subs[sub_id] = q
            # Cancela grace period se estava prestes a fechar.
            if self._grace_task and not self._grace_task.done():
                self._grace_task.cancel()
                self._grace_task = None
        return sub_id, q

    async def unsubscribe(self, sub_id: int) -> None:
        async with self._lock:
            self._subs.pop(sub_id, None)
            if not self._subs:
                # Nenhum subscriber restante — agendar fechamento com grace period.
                self._grace_task = asyncio.create_task(self._close_after_grace())

    async def _close_after_grace(self) -> None:
        await asyncio.sleep(_GRACE_SECONDS)
        async with self._lock:
            if self._subs:
                return  # Novo subscriber chegou durante o grace period.
            _listeners.pop(self._channel, None)
            conn = self._conn
            self._conn = None
        if conn and not conn.is_closed():
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                pass
        logger.debug("shared_listener.closed", channel=self._channel)


class DefinitionEventService:
    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    async def publish_within_tx(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        client_mutation_id: str | None = None,
    ) -> WorkflowDefinitionEvent:
        """Persiste evento e emite pg_notify DENTRO da transação corrente (sem commit).

        Garante atomicidade com a mutação do caller: ambos commit ou rollback juntos.
        pg_notify é enfileirado pelo PostgreSQL e só entregue após o commit da transação,
        então subscribers SSE só recebem a notificação quando a mutação já está durável.
        """
        event = WorkflowDefinitionEvent(
            workflow_id=workflow_id,
            event_type=event_type,
            payload=payload,
            client_mutation_id=client_mutation_id,
        )
        db.add(event)
        await db.flush()  # popula id e seq (via sequência do servidor)

        notify_payload = json.dumps(
            {
                "seq": event.seq,
                "event_id": str(event.id),
                "workflow_id": str(workflow_id),
                "event_type": event_type,
                "payload": payload,
                "client_mutation_id": client_mutation_id,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            default=str,
        )

        channel = _channel(workflow_id)
        await db.execute(
            text("SELECT pg_notify(:ch, :pl)"),
            {"ch": channel, "pl": notify_payload},
        )

        logger.debug(
            "definition_event.within_tx",
            workflow_id=str(workflow_id),
            event_type=event_type,
            seq=event.seq,
        )
        return event

    async def publish(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        client_mutation_id: str | None = None,
    ) -> WorkflowDefinitionEvent:
        """Persiste evento, emite pg_notify e comita (para callers sem transação aberta)."""
        event = await self.publish_within_tx(
            db,
            workflow_id=workflow_id,
            event_type=event_type,
            payload=payload,
            client_mutation_id=client_mutation_id,
        )
        await db.commit()
        logger.debug(
            "definition_event.published",
            workflow_id=str(workflow_id),
            event_type=event_type,
            seq=event.seq,
        )
        return event

    # ------------------------------------------------------------------
    # Leitura (replay para ?since=<seq>)
    # ------------------------------------------------------------------

    async def get_events_since(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        since_seq: int,
    ) -> list[WorkflowDefinitionEvent]:
        """Retorna eventos com seq > since_seq, em ordem crescente, limitado a 500."""
        stmt = (
            select(WorkflowDefinitionEvent)
            .where(
                WorkflowDefinitionEvent.workflow_id == workflow_id,
                WorkflowDefinitionEvent.seq > since_seq,
            )
            .order_by(WorkflowDefinitionEvent.seq.asc())
            .limit(_MAX_REPLAY_ROWS)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # SSE stream (gerador assíncrono)
    # ------------------------------------------------------------------

    async def sse_stream(
        self,
        *,
        workflow_id: UUID,
        since_seq: int | None,
    ) -> AsyncGenerator[str, None]:
        """
        Gerador SSE para o endpoint GET .../definition/events.

        Fluxo:
          1. Abre conexão raw asyncpg e LISTEN no canal.
          2. Replays eventos perdidos (since_seq fornecido).
          3. Transmite notificações à medida que chegam.
          4. Emite :keepalive a cada 20s para manter a conexão.
          5. Fecha conexão ao cancelar (cliente desconecta).
        """
        channel = _channel(workflow_id)

        # Obtém (ou cria) o SharedListener para este canal.
        if channel not in _listeners:
            _listeners[channel] = SharedListener(channel)
        listener = _listeners[channel]

        sub_id, queue = await listener.subscribe()
        try:
            # Replay: busca eventos perdidos numa sessão temporária.
            if since_seq is not None:
                from app.db.session import async_session_factory

                async with async_session_factory() as replay_db:
                    rows = await self.get_events_since(
                        replay_db,
                        workflow_id=workflow_id,
                        since_seq=since_seq,
                    )
                for row in rows:
                    yield _format_sse(row.seq, row.event_type, _row_to_dict(row))

            # Streaming em tempo real
            while True:
                try:
                    raw = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                    if raw == _OVERFLOW_SENTINEL:
                        logger.warning(
                            "definition_event.stream_overflow",
                            workflow_id=str(workflow_id),
                        )
                        return  # Força reconexão do cliente
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("definition_event.bad_notify_payload", raw=raw[:200])
                        continue
                    yield _format_sse(data["seq"], data["event_type"], data)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "definition_event.stream_error", workflow_id=str(workflow_id)
            )
        finally:
            await listener.unsubscribe(sub_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_sse(seq: int, event_type: str, data: dict[str, Any]) -> str:
    """Formata uma mensagem SSE completa incluindo id, event e data."""
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {seq}\nevent: {event_type}\ndata: {body}\n\n"


def _row_to_dict(row: WorkflowDefinitionEvent) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "event_id": str(row.id),
        "workflow_id": str(row.workflow_id),
        "event_type": row.event_type,
        "payload": row.payload,
        "client_mutation_id": row.client_mutation_id,
        "ts": row.created_at.isoformat() if row.created_at else None,
    }


definition_event_service = DefinitionEventService()
