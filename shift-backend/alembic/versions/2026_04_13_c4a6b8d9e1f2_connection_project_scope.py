"""connection project scope

Revision ID: c4a6b8d9e1f2
Revises: 03902dfb62c4
Create Date: 2026-04-13 20:30:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4a6b8d9e1f2"
down_revision: Union[str, None] = "03902dfb62c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_connections_project_id",
        "connections",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_connections_project_id"),
        "connections",
        ["project_id"],
        unique=False,
    )
    op.alter_column(
        "connections",
        "workspace_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_connection_owner_not_null",
        "connections",
        "workspace_id IS NOT NULL OR project_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_connection_single_owner",
        "connections",
        "NOT (workspace_id IS NOT NULL AND project_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_connection_single_owner", "connections", type_="check")
    op.drop_constraint("ck_connection_owner_not_null", "connections", type_="check")
    op.alter_column(
        "connections",
        "workspace_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.drop_index(op.f("ix_connections_project_id"), table_name="connections")
    op.drop_constraint("fk_connections_project_id", "connections", type_="foreignkey")
    op.drop_column("connections", "project_id")
