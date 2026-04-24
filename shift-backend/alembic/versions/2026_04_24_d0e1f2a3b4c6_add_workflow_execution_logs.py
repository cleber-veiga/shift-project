"""add workflow_execution_logs table

Revision ID: d0e1f2a3b4c6
Revises: c9d0e1f2a3b5
Create Date: 2026-04-24

Cria a tabela ``workflow_execution_logs`` para log estruturado granular
durante a execucao de workflows. Granularidade maior que ``WorkflowNodeExecution``:
um no pode emitir varios eventos (info, warning, error) ao longo da sua execucao.

Usado para troubleshooting remoto de consultores via endpoint GET
``/executions/{id}/logs`` (JSON ou texto). Nao armazena payloads — apenas
metadados + amostras com PII mascarada em caso de erro de conversao.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "d0e1f2a3b4c6"
down_revision = "c9d0e1f2a3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_execution_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.String(255),
            nullable=True,
            comment="ID do no emitente. None para eventos de execucao global.",
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "level",
            sa.String(16),
            nullable=False,
            server_default="info",
            comment="info | warning | error",
        ),
        sa.Column(
            "message",
            sa.Text,
            nullable=False,
        ),
        sa.Column(
            "context",
            JSONB,
            nullable=True,
            comment="Metadados estruturados: chunk_idx, rows_sample (PII masked), error_type.",
        ),
    )
    op.create_index(
        "ix_workflow_execution_logs_execution_id",
        "workflow_execution_logs",
        ["execution_id"],
    )
    op.create_index(
        "ix_workflow_execution_logs_timestamp",
        "workflow_execution_logs",
        ["timestamp"],
    )
    # Indice composto para a consulta principal do endpoint /logs
    # (filtra por execution_id + ordena por timestamp).
    op.create_index(
        "ix_workflow_execution_logs_exec_ts",
        "workflow_execution_logs",
        ["execution_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_execution_logs_exec_ts", table_name="workflow_execution_logs")
    op.drop_index("ix_workflow_execution_logs_timestamp", table_name="workflow_execution_logs")
    op.drop_index("ix_workflow_execution_logs_execution_id", table_name="workflow_execution_logs")
    op.drop_table("workflow_execution_logs")
