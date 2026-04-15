"""
Modelo ORM para consultas SQL salvas.

As queries ficam vinculadas a (player_id + database_type),
tornando-as reutilizáveis em qualquer conexão do mesmo concorrente e tipo de banco.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SavedQuery(Base):
    """Consulta SQL salva para reutilização."""

    __tablename__ = "saved_queries"
    __table_args__ = (
        UniqueConstraint("player_id", "database_type", "name", name="uq_saved_query_player_type_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_players.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    database_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    query: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
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
