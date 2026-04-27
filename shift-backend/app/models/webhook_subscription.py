"""Modelos ORM de webhooks de saida (notificacao de clientes).

Conceito
--------
Diferente dos webhooks de **entrada** (no `webhook` do workflow, em
``app.models.workflow.WebhookTestCapture`` + endpoint /webhook/{path}),
estes sao webhooks de **saida**: o Shift POSTa para uma URL fornecida
pelo cliente quando uma execucao termina.

Tres tabelas:

- ``webhook_subscriptions``: registro do cliente — URL, eventos, secret HMAC.
- ``webhook_deliveries``: cada tentativa de entrega (retry incluso). Funciona
  como fila — o worker periodico escolhe linhas com ``status='pending'``
  e ``next_attempt_at <= now()``.
- ``webhook_dead_letters``: entrada finalizada como falha apos esgotar
  retries OU 4xx imediato. Mantem o payload completo + cabecalhos da
  ultima tentativa para replay manual.

Decisoes de design
------------------
- ``secret`` fica em texto puro NA COLUNA — o segredo HMAC precisa ser
  conhecido pelo backend e pelo cliente. Mascaramos no log via
  ``log_sanitizer`` (Prompt 6.2). Em produciao, o operador pode optar
  por criptografia at-rest no Postgres (TDE/pgcrypto) — ortogonal a
  esta camada.
- ``events`` e um array Postgres de strings, nao um JSONB, para que o
  ``ANY()`` SQL filtre eficientemente sem desserializar JSON. A lista
  oficial de eventos (``execution.completed``, ``execution.failed``,
  ``execution.cancelled``) e validada no schema Pydantic, nao na DB —
  permite adicionar novos eventos sem migracao.
- ``last_attempt_at`` e ``last_status_code`` em ``webhook_subscriptions``
  sao denormalizadores para a UI listar "ultimo status" sem JOIN — mais
  caro em writes, mas ler dashboards e o caso comum.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# Eventos suportados — fonte unica de verdade. Schemas validam contra esta lista.
SUPPORTED_EVENTS: tuple[str, ...] = (
    "execution.completed",
    "execution.failed",
    "execution.cancelled",
)


class WebhookSubscription(Base):
    """Inscricao de um cliente em eventos de execucao do workspace.

    Uma inscricao recebe POSTs para ``url`` quando uma execucao do
    workspace gera um evento contido em ``events``. Cada POST inclui
    header ``X-Shift-Signature`` (HMAC-SHA256 do body com ``secret``).
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(
        String(2048), nullable=False,
        comment="URL HTTPS do cliente — sera invocada com POST no evento.",
    )
    events: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False,
        comment="Lista de eventos assinados (ex: execution.completed).",
    )
    secret: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Segredo HMAC-SHA256 — gerado pelo backend, exibido apenas no create.",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Descricao livre fornecida pelo cliente (ex: 'CRM principal').",
    )
    active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Denormalizers para UI — atualizados pelo dispatch_service ao final
    # de cada tentativa (sucesso ou falha terminal).
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_status_code: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="HTTP status code da ultima tentativa (None se ainda nao tentou).",
    )

    deliveries: Mapped[list["WebhookDelivery"]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )


class WebhookDelivery(Base):
    """Tentativa(s) de entrega de um evento para uma subscription.

    Atua como fila: o worker periodico (``webhook_dispatch_loop``) faz
    ``SELECT ... WHERE status='pending' AND next_attempt_at <= now() FOR
    UPDATE SKIP LOCKED`` e processa cada linha. Apos ``max_attempts``
    falhas (ou 4xx imediato), ``status`` vira ``'failed'`` e uma linha
    paralela aparece em ``webhook_dead_letters`` para replay manual.

    Estados:
    - ``pending``    : aguardando proxima tentativa.
    - ``in_flight`` : em entrega (FOR UPDATE adquirido).
    - ``delivered`` : recebeu 2xx do cliente.
    - ``failed``    : esgotou retries ou recebeu 4xx (sem retry).
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False,
        comment="Body que sera serializado e POSTado. Imutavel apos criar.",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=6, server_default="6",
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        index=True,
    )
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    # Linkagem opcional para a execucao que gerou o evento — facilita filtro
    # na UI ("entregas para a execucao X"). Pode ser NULL para test deliveries.
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    # W3C Trace Context (Tarefa 3 do hardening 6.2/6.3) — capturado no
    # ``enqueue_for_event`` para que o span ``webhook.dispatch`` no worker
    # vire child do span da execucao upstream, mesmo cruzando processos /
    # event loops / workers Celery. NULL quando tracing esta desligado ou
    # nao havia span ativo no momento do enqueue.
    trace_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )

    subscription: Mapped["WebhookSubscription"] = relationship(
        back_populates="deliveries", lazy="raise_on_sql"
    )


class WebhookDeadLetter(Base):
    """Delivery que falhou definitivamente — preserva contexto pra replay.

    Diferente de ``DeadLetterEntry`` (Sprint 4.x), que e sobre LINHAS de
    extracao que falharam num node — este e dead-letter de **entrega de
    webhook**. Usamos uma tabela separada porque os campos sao distintos
    (URL alvo, status code HTTP, body que iria ser POSTado).
    """

    __tablename__ = "webhook_dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_deliveries.id", ondelete="SET NULL"),
        nullable=True,
        comment="Delivery que originou. NULL apos replay que dispara nova entrega.",
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Setado quando o operador faz replay (cria nova delivery).",
    )
