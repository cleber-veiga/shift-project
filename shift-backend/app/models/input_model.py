"""
Modelo ORM: InputModel (modelo/template de entrada de dados).

Define a estrutura esperada de um arquivo (Excel ou CSV) para
importacao de dados em workflows. Garante que os dados carregados
respeitem colunas, tipos e obrigatoriedade definidos pelo criador.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class InputModel(Base):
    """Template reutilizavel que define a estrutura esperada de um arquivo de entrada."""

    __tablename__ = "input_models"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_input_model_workspace_name"),
    )

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'excel' | 'csv'
    schema_def: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="input_models")
    rows: Mapped[list["InputModelRow"]] = relationship(
        back_populates="input_model",
        cascade="all, delete-orphan",
        order_by="InputModelRow.row_order",
    )
