"""Add player_id to connections and widen database column to TEXT.

- connections.player_id (UUID NULLABLE FK workspace_players ON DELETE SET NULL)
  Vincula a conexao ao concorrente correspondente (apenas categorização).

- connections.database alterado de VARCHAR(255) para TEXT
  Suporta caminhos Windows longos para Firebird.

Revision ID: b1c2d3e4f5a6
Revises: a3f7d2e981bc
Create Date: 2026-04-14
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a3f7d2e981bc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Amplia connections.database de VARCHAR(255) para TEXT
    op.alter_column(
        "connections",
        "database",
        type_=sa.Text(),
        existing_type=sa.String(255),
        existing_nullable=False,
    )

    # 2. Adiciona player_id em connections
    op.add_column(
        "connections",
        sa.Column(
            "player_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index("ix_connections_player_id", "connections", ["player_id"])
    op.create_foreign_key(
        "fk_connections_player_id",
        "connections",
        "workspace_players",
        ["player_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_connections_player_id", "connections", type_="foreignkey")
    op.drop_index("ix_connections_player_id", table_name="connections")
    op.drop_column("connections", "player_id")

    op.alter_column(
        "connections",
        "database",
        type_=sa.String(255),
        existing_type=sa.Text(),
        existing_nullable=False,
    )
