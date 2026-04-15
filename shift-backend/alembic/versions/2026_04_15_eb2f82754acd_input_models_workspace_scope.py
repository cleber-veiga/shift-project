"""Move input_models from project to workspace scope.

Revision ID: eb2f82754acd
Revises: 36f558e9f79e
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "eb2f82754acd"
down_revision = "36f558e9f79e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old constraints and indexes
    op.drop_constraint("uq_input_model_project_name", "input_models", type_="unique")
    op.drop_constraint("input_models_project_id_fkey", "input_models", type_="foreignkey")
    op.drop_index("ix_input_models_project_id", table_name="input_models")
    op.drop_column("input_models", "project_id")

    # Add workspace_id
    op.add_column(
        "input_models",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "input_models_workspace_id_fkey",
        "input_models",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_input_models_workspace_id", "input_models", ["workspace_id"])
    op.create_unique_constraint(
        "uq_input_model_workspace_name", "input_models", ["workspace_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_input_model_workspace_name", "input_models", type_="unique")
    op.drop_index("ix_input_models_workspace_id", table_name="input_models")
    op.drop_constraint("input_models_workspace_id_fkey", "input_models", type_="foreignkey")
    op.drop_column("input_models", "workspace_id")

    op.add_column(
        "input_models",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "input_models_project_id_fkey",
        "input_models",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_input_models_project_id", "input_models", ["project_id"])
    op.create_unique_constraint(
        "uq_input_model_project_name", "input_models", ["project_id", "name"]
    )
