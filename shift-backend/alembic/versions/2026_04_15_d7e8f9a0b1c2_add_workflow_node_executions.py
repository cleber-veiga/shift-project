"""add workflow_node_executions table

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_executions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "execution_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("node_id", sa.String(255), nullable=False, comment="ID do no no React Flow"),
        sa.Column("node_type", sa.String(50), nullable=False, comment="Tipo do no"),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="running",
            comment="running, success, error, skipped",
        ),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("row_count_in", sa.Integer, nullable=True, comment="Linhas recebidas"),
        sa.Column("row_count_out", sa.Integer, nullable=True, comment="Linhas produzidas/gravadas"),
        sa.Column(
            "output_summary",
            sa.dialects.postgresql.JSONB,
            nullable=True,
            comment="Metricas do no (sem rows[])",
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Index para buscar nos de uma execucao rapidamente
    op.create_index(
        "ix_wf_node_exec_exec_id_node_id",
        "workflow_node_executions",
        ["execution_id", "node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_wf_node_exec_exec_id_node_id", table_name="workflow_node_executions")
    op.drop_table("workflow_node_executions")
