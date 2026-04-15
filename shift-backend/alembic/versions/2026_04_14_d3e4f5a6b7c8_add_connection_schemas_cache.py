"""Add connection_schemas cache table.

Tabela para cache de schemas de bancos de dados.
Evita consultas repetidas ao banco externo — cache é válido por 3 meses.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connection_schemas",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("schema_data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id"),
    )
    op.create_index(
        "ix_connection_schemas_connection_id",
        "connection_schemas",
        ["connection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_connection_schemas_connection_id", table_name="connection_schemas")
    op.drop_table("connection_schemas")
