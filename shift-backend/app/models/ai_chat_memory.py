"""
Modelo ORM para memorias do Assistente SQL.

Armazena queries que o usuario aplicou ao editor a partir do chat —
servem como exemplos de estilo/convencoes para prompts futuros.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiChatMemory(Base):
    """Query SQL util que o usuario aplicou no editor a partir do Assistente."""

    __tablename__ = "ai_chat_memories"
    __table_args__ = (
        # Evita duplicar memorias identicas por usuario/conexao
        UniqueConstraint(
            "connection_id",
            "user_id",
            "query_hash",
            name="uq_ai_chat_memory_conn_user_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    # Hash SHA-256 hex (64 chars) da query normalizada, para deduplicar
    query_hash: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
