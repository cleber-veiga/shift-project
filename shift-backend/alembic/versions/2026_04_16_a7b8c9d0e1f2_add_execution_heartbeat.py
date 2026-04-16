"""add heartbeat column and index to workflow_executions

Adiciona ``updated_at`` (heartbeat) em ``workflow_executions`` para
detecção de execuções órfãs após crash, e um índice composto em
``(status, updated_at)`` para acelerar a query de limpeza no startup.

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-04-16 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


revision = "a7b8c9d0e1f2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_workflow_executions_status_updated",
        "workflow_executions",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_executions_status_updated",
        table_name="workflow_executions",
    )
    op.drop_column("workflow_executions", "updated_at")
