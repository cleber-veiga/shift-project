"""drop prefect_flow_run_id from workflow_executions

A coluna era preenchida pela integracao com Prefect, que foi substituida
pelo engine asyncio interno. Removida junto com a dependencia.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-16 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("workflow_executions", "prefect_flow_run_id")


def downgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "prefect_flow_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
