"""add dead_letter_entries table

Revision ID: c6d7e8f9a0bb
Revises: b5c6d7e8f9aa
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c6d7e8f9a0bb"
down_revision = "b5c6d7e8f9aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dead_letter_entries",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "execution_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dead_letter_entries_execution_id",
        "dead_letter_entries",
        ["execution_id"],
    )
    op.create_index(
        "ix_dead_letter_entries_created_at",
        "dead_letter_entries",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dead_letter_entries_created_at", table_name="dead_letter_entries")
    op.drop_index("ix_dead_letter_entries_execution_id", table_name="dead_letter_entries")
    op.drop_table("dead_letter_entries")
