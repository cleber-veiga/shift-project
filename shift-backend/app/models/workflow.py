"""
Modelos ORM: Workflow e WorkflowExecution.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Workflow(Base):
    """Definicao de um workflow vinculado a um projeto ou workspace (template)."""

    __tablename__ = "workflows"

    __table_args__ = (
        CheckConstraint(
            "project_id IS NOT NULL OR workspace_id IS NOT NULL",
            name="ck_workflow_owner_not_null",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="workflows")
    workspace: Mapped["Workspace"] = relationship(back_populates="workflows")
    executions: Mapped[list["WorkflowExecution"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class WorkflowExecution(Base):
    """Registro de uma execucao de workflow."""

    __tablename__ = "workflow_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    prefect_flow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    workflow: Mapped["Workflow"] = relationship(back_populates="executions")
    node_executions: Mapped[list["WorkflowNodeExecution"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
    )


class WorkflowNodeExecution(Base):
    """Registro de execucao de um no individual dentro de um run de workflow."""

    __tablename__ = "workflow_node_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="ID do no no React Flow (ex: node_1776266083668_2)",
    )
    node_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Tipo do no (sql_database, mapper, bulk_insert, etc.)",
    )
    label: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Label legivel configurado pelo usuario",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running",
        comment="running, success, error, skipped",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    row_count_in: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Linhas recebidas do upstream",
    )
    row_count_out: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Linhas produzidas / gravadas",
    )
    output_summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Metricas do no (sem rows[] para economizar espaco)",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    execution: Mapped["WorkflowExecution"] = relationship(
        back_populates="node_executions",
    )
