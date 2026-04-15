"""Add saved_queries table.

Consultas SQL salvas vinculadas a (player_id + database_type).
Reutilizáveis em qualquer conexão do mesmo concorrente e tipo de banco.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-04-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_queries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column("database_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["workspace_players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "database_type", "name", name="uq_saved_query_player_type_name"),
    )
    op.create_index("ix_saved_queries_workspace_id", "saved_queries", ["workspace_id"])
    op.create_index("ix_saved_queries_player_id", "saved_queries", ["player_id"])
    op.create_index("ix_saved_queries_created_by_id", "saved_queries", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_queries_created_by_id", table_name="saved_queries")
    op.drop_index("ix_saved_queries_player_id", table_name="saved_queries")
    op.drop_index("ix_saved_queries_workspace_id", table_name="saved_queries")
    op.drop_table("saved_queries")
