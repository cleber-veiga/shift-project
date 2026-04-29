"""
Modelos ORM: Workflow e WorkflowExecution.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="workflows", lazy="raise_on_sql")
    workspace: Mapped["Workspace"] = relationship(back_populates="workflows", lazy="raise_on_sql")
    executions: Mapped[list["WorkflowExecution"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise_on_sql",
    )
    versions: Mapped[list["WorkflowVersion"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowVersion.version",
        lazy="raise_on_sql",
    )


class WorkflowVersion(Base):
    """Snapshot imutavel de um workflow publicado para uso como sub-workflow."""

    __tablename__ = "workflow_versions"

    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "version", name="uq_workflow_versions_wf_version"
        ),
    )

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
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_schema: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    output_schema: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    workflow: Mapped["Workflow"] = relationship(back_populates="versions", lazy="raise_on_sql")


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
    triggered_by: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="manual",
        server_default="manual",
        index=True,
        comment="Origem do disparo: manual (UI via /test), api (POST /execute), cron, webhook",
    )
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment=(
            "Snapshot imutavel da definicao renderizada (pos-Jinja2) com "
            "valores de variaveis 'secret' redatados como '<REDACTED>'. "
            "Audit trail + replay deterministico."
        ),
    )
    template_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="SHA-256 hex de template_snapshot. Determinastico para mesma entrada.",
    )
    rendered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Timestamp do render — anterior ao inicio efetivo do runner.",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    plan_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment=(
            "ExecutionPlanSnapshot: topological levels, node_count, edge_count, "
            "predicted_strategies. Capturado antes do primeiro nó rodar (Fase 4)."
        ),
    )

    workflow: Mapped["Workflow"] = relationship(back_populates="executions", lazy="raise_on_sql")
    node_executions: Mapped[list["WorkflowNodeExecution"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    dead_letter_entries: Mapped[list["DeadLetterEntry"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
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
        lazy="raise_on_sql",
    )


class DeadLetterEntry(Base):
    """Linha em dead-letter para payloads que nao puderam ser processados."""

    __tablename__ = "dead_letter_entries"

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
        String(255),
        nullable=False,
        comment="ID do no que originalmente falhou / gerou o dead-letter.",
    )
    error_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Snapshot do payload problematico armazenado para retry manual.",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    execution: Mapped["WorkflowExecution"] = relationship(
        back_populates="dead_letter_entries",
        lazy="raise_on_sql",
    )


class WebhookTestCapture(Base):
    """Buffer de curta duracao para capturas da URL de teste do webhook.

    Cada linha representa a ultima requisicao recebida por
    (workflow_id, node_id) na rota /webhook-test. A UI (botao
    "Listen for test event") faz polling ou aguarda notificacao
    via asyncio.Event para pegar o payload. TTL curto via
    expires_at + limpeza em background.
    """

    __tablename__ = "webhook_test_captures"

    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "node_id", name="uq_webhook_test_workflow_node"
        ),
    )

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
    node_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    headers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    query_params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    body: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    raw_body_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowExecutionLog(Base):
    """Log estruturado de eventos de execucao — granularidade maior que
    ``WorkflowNodeExecution`` (que agrega 1 linha por no).

    Esta tabela armazena mensagens individuais (info, warning, error) emitidas
    durante a execucao — um no pode gerar varios logs. Usado para troubleshooting
    remoto de consultores: mostra exatamente o que aconteceu, com timestamps
    e contexto estruturado, sem precisar de acesso SSH ao servidor.

    Nao armazena payloads de dados — apenas metadados. Se um no falha com
    erro de conversao de tipo, as linhas-amostra ficam em ``context`` com PII
    mascarada.
    """

    __tablename__ = "workflow_execution_logs"

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
    node_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="ID do no emitente. None para eventos de execucao global.",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="info",
        comment="info | warning | error",
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Metadados estruturados: chunk_idx, rows_sample (PII masked), error_type.",
    )


class WorkflowCheckpoint(Base):
    """Checkpoint de um no para retomada de execucao falhada.

    Quando ``checkpoint_enabled=true`` no config do no, o output e persistido
    aqui (com caminho DuckDB copiado para local persistente) e pode ser
    reutilizado por uma execucao de retry sem re-executar o no.
    """

    __tablename__ = "workflow_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Execucao que gerou este checkpoint.",
    )
    node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="ID do no React Flow que produziu o output.",
    )
    result_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Result dict do processador com caminhos DuckDB persistentes.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Checkpoint expira automaticamente (default: 7 dias apos criacao).",
    )
    used_by_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID da execucao de retry que consumiu este checkpoint.",
    )
