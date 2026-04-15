"""add is_public and created_by_id to connections

Revision ID: a3f7d2e981bc
Revises: 7c1f2d4e6a8b
Create Date: 2026-04-14 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7d2e981bc"
down_revision: Union[str, None] = "7c1f2d4e6a8b"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    # is_public — visibilidade da conexao; existentes ficam publicas por padrao
    op.add_column(
        "connections",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # created_by_id — quem cadastrou; nullable para registros existentes
    op.add_column(
        "connections",
        sa.Column(
            "created_by_id",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_connections_created_by_id_users",
        "connections",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_connections_created_by_id"),
        "connections",
        ["created_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_connections_created_by_id"), table_name="connections")
    op.drop_constraint("fk_connections_created_by_id_users", "connections", type_="foreignkey")
    op.drop_column("connections", "created_by_id")
    op.drop_column("connections", "is_public")
