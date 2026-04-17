"""add triggered_by to workflow_executions

Adiciona a coluna ``triggered_by`` em ``workflow_executions`` para
registrar a origem do disparo (manual, api, cron, webhook) e cria os
indices usados pela listagem da aba Executions na UI.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-04-16 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "triggered_by",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
            comment="Origem do disparo: manual, api, cron, webhook",
        ),
    )
    op.create_index(
        "ix_workflow_executions_triggered_by",
        "workflow_executions",
        ["triggered_by"],
    )
    op.create_index(
        "ix_workflow_executions_workflow_id_started_at",
        "workflow_executions",
        ["workflow_id", "started_at"],
    )
    op.create_index(
        "ix_workflow_executions_status",
        "workflow_executions",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_executions_status",
        table_name="workflow_executions",
    )
    op.drop_index(
        "ix_workflow_executions_workflow_id_started_at",
        table_name="workflow_executions",
    )
    op.drop_index(
        "ix_workflow_executions_triggered_by",
        table_name="workflow_executions",
    )
    op.drop_column("workflow_executions", "triggered_by")
