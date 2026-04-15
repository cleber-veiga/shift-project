"""
Modelo ORM: InputModelRow — linhas de dados armazenadas em um InputModel.

Permite que um InputModel funcione como tabela interna do sistema,
contendo dados de referência (ex: cadastro de CFOP) que podem ser
utilizados como source em workflows.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class InputModelRow(Base):
    """Uma linha de dados pertencente a um InputModel."""

    __tablename__ = "input_model_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    input_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("input_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    input_model: Mapped["InputModel"] = relationship(back_populates="rows")
