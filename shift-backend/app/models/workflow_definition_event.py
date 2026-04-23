"""
Modelo ORM: WorkflowDefinitionEvent.

Cada linha representa uma mutacao atômica na definition de um workflow
(node adicionado, removido, aresta criada, variáveis alteradas, etc.).
Usado para:
  - Replay de eventos perdidos (?since=<seq>) ao reconectar o SSE.
  - Auditoria de modificações feitas pelo Platform Agent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Sequence, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

# Sequência global que garante ordenação mesmo com inserções concorrentes.
_SEQ = Sequence("workflow_definition_events_seq_seq")


class WorkflowDefinitionEvent(Base):
    """Evento imutável de modificação da definition de um workflow."""

    __tablename__ = "workflow_definition_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    client_mutation_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    seq: Mapped[int] = mapped_column(
        BigInteger,
        _SEQ,
        nullable=False,
        unique=True,
        server_default=_SEQ.next_value(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
