"""Add include_schemas to connections.

Permite configurar schemas adicionais a serem incluídos na introspecção
de catálogo. As tabelas desses schemas aparecem como SCHEMA.TABELA.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-04-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column(
            "include_schemas",
            postgresql.JSONB(),
            nullable=True,
            comment="Lista de schemas adicionais a incluir no catálogo (ex: [\"VIASOFTBASE\"])",
        ),
    )


def downgrade() -> None:
    op.drop_column("connections", "include_schemas")
