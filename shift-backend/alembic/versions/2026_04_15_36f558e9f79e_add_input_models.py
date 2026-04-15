"""Add input_models table.

Cria a tabela de modelos de entrada para templates de Excel/CSV,
com schema JSONB definindo abas e colunas esperadas.

Revision ID: 36f558e9f79e
Revises: f5a6b7c8d9e0
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "36f558e9f79e"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "input_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("schema_def", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("project_id", "name", name="uq_input_model_project_name"),
    )
    op.create_index("ix_input_models_project_id", "input_models", ["project_id"])
    op.create_index("ix_input_models_created_by_id", "input_models", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_input_models_created_by_id", table_name="input_models")
    op.drop_index("ix_input_models_project_id", table_name="input_models")
    op.drop_table("input_models")
