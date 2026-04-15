"""workflow templates

Revision ID: b7e8f9a0c1d2
Revises: 6f5b4c2a9d10
Create Date: 2026-04-13 18:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e8f9a0c1d2"
down_revision: Union[str, None] = "6f5b4c2a9d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Torna project_id nullable
    op.alter_column("workflows", "project_id", existing_type=sa.UUID(), nullable=True)

    # 2. Adiciona workspace_id (FK para workspaces, nullable)
    op.add_column(
        "workflows",
        sa.Column("workspace_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_workflows_workspace_id",
        "workflows",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_workflows_workspace_id",
        "workflows",
        ["workspace_id"],
        unique=False,
    )

    # 3. Adiciona is_template e is_published
    op.add_column(
        "workflows",
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "workflows",
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # 4. Adiciona CheckConstraint: project_id OR workspace_id deve ser nao-nulo
    op.create_check_constraint(
        "ck_workflow_owner_not_null",
        "workflows",
        "project_id IS NOT NULL OR workspace_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_owner_not_null", "workflows", type_="check")
    op.drop_column("workflows", "is_published")
    op.drop_column("workflows", "is_template")
    op.drop_index("ix_workflows_workspace_id", table_name="workflows")
    op.drop_constraint("fk_workflows_workspace_id", "workflows", type_="foreignkey")
    op.drop_column("workflows", "workspace_id")
    op.alter_column("workflows", "project_id", existing_type=sa.UUID(), nullable=False)
