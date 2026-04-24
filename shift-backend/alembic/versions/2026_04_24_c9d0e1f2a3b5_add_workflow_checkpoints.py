"""add workflow_checkpoints table

Revision ID: c9d0e1f2a3b5
Revises: b8c9d0e1f2a4
Create Date: 2026-04-24

Cria a tabela ``workflow_checkpoints`` para suporte a retomada de execucoes
falhadas a partir do ultimo no com sucesso (Sprint 3.1).

Cada linha representa o output persistente de um no com ``checkpoint_enabled=true``,
incluindo o caminho do arquivo DuckDB copiado para local nao-temporario.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c9d0e1f2a3b5"
down_revision = "b8c9d0e1f2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_checkpoints",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
            comment="Execucao que gerou este checkpoint.",
        ),
        sa.Column(
            "node_id",
            sa.String(255),
            nullable=False,
            comment="ID do no React Flow que produziu o output.",
        ),
        sa.Column(
            "result_json",
            JSONB,
            nullable=False,
            comment="Result dict do processador com caminhos DuckDB persistentes.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Checkpoint expira automaticamente (default: 7 dias apos criacao).",
        ),
        sa.Column(
            "used_by_execution_id",
            UUID(as_uuid=True),
            nullable=True,
            comment="ID da execucao de retry que consumiu este checkpoint.",
        ),
    )
    op.create_index(
        "ix_workflow_checkpoints_source_execution_id",
        "workflow_checkpoints",
        ["source_execution_id"],
    )
    op.create_index(
        "ix_workflow_checkpoints_expires_at",
        "workflow_checkpoints",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_checkpoints_expires_at", table_name="workflow_checkpoints")
    op.drop_index("ix_workflow_checkpoints_source_execution_id", table_name="workflow_checkpoints")
    op.drop_table("workflow_checkpoints")
