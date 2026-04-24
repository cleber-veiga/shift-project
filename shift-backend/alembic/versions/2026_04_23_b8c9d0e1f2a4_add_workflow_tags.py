"""add tags column to workflows

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f3
Create Date: 2026-04-23

Adiciona a coluna ``tags`` (JSONB, default ``[]``) na tabela ``workflows``
para permitir marcadores/agrupamentos pesquisaveis. Os valores sao sempre
armazenados em MAIUSCULO (normalizado pelo Pydantic antes da persistencia).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b8c9d0e1f2a4"
down_revision = "a7b8c9d0e1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "tags",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workflows", "tags")
