"""
Modelo ORM para o log de auditoria do Platform Agent.

Rastro imutavel de toda acao executada pelo agente apos aprovacao humana.
Append-only por design — nao deve ser atualizado apos criacao.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentAuditLog(Base):
    """Registro imutavel de execucao de ferramenta pelo Platform Agent."""

    __tablename__ = "agent_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_threads.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_approvals.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    tool_arguments: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tool_result_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_metadata: Mapped[dict | None] = mapped_column(
        "log_metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
