"""add input_model_rows

Revision ID: a409361ac779
Revises: eb2f82754acd
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a409361ac779"
down_revision = "eb2f82754acd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "input_model_rows",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("input_model_id", sa.UUID(), nullable=False),
        sa.Column("row_order", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["input_model_id"], ["input_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_input_model_rows_input_model_id", "input_model_rows", ["input_model_id"])


def downgrade() -> None:
    op.drop_index("ix_input_model_rows_input_model_id", table_name="input_model_rows")
    op.drop_table("input_model_rows")
