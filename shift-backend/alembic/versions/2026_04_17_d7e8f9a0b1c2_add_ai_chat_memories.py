"""add ai_chat_memories table

Revision ID: d7e8f9a0b1cc
Revises: c6d7e8f9a0bb
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d7e8f9a0b1cc"
down_revision = "c6d7e8f9a0bb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_memories",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "connection_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "connection_id",
            "user_id",
            "query_hash",
            name="uq_ai_chat_memory_conn_user_hash",
        ),
    )
    op.create_index(
        "ix_ai_chat_memories_connection_id",
        "ai_chat_memories",
        ["connection_id"],
    )
    op.create_index(
        "ix_ai_chat_memories_user_id",
        "ai_chat_memories",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_chat_memories_user_id", table_name="ai_chat_memories")
    op.drop_index("ix_ai_chat_memories_connection_id", table_name="ai_chat_memories")
    op.drop_table("ai_chat_memories")
