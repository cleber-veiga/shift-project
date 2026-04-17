"""
Modelo ORM: CustomNodeDefinition.

Um "no personalizado" e um blueprint reutilizavel que descreve uma
composicao de escritas em multiplas tabelas relacionadas do sistema de
destino (ex: NOTA + NOTAITEM + NOTAICMS numa unica transacao). Cada
definicao aparece na paleta do editor de workflow como se fosse um no
nativo — mas no backend todas usam o mesmo processor ``composite_insert``
parametrizado pelo blueprint.

O blueprint e persistido em JSONB. Quando o usuario arrasta um no
personalizado para o canvas, o blueprint e copiado (snapshot) para
``node.data.blueprint`` — o processador le dali em tempo de execucao,
sem depender do estado atual desta tabela. Isso garante imutabilidade
por workflow: editar a definicao nao quebra execucoes antigas.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CustomNodeDefinition(Base):
    """Blueprint reutilizavel de um no composto da paleta do workflow."""

    __tablename__ = "custom_node_definitions"
    __table_args__ = (
        CheckConstraint(
            "workspace_id IS NOT NULL OR project_id IS NOT NULL",
            name="ck_custom_node_owner_not_null",
        ),
        CheckConstraint(
            "NOT (workspace_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_custom_node_single_owner",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "name",
            "version",
            name="uq_custom_node_scope_name_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="output"
    )
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="composite_insert",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    blueprint: Mapped[dict] = mapped_column(JSONB, nullable=False)
    form_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
