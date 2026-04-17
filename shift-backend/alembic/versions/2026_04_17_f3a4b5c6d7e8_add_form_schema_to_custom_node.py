"""add form_schema to custom_node_definitions

Adiciona coluna JSONB ``form_schema`` opcional em
``custom_node_definitions``. Metadados de UI que descrevem como o
formulario do no e apresentado ao usuario final no editor de fluxo
(labels, help, campos ocultos, campo required, auto-match sugerido).

Nao afeta a execucao — o backend de composite_insert continua lendo
apenas ``blueprint`` + ``field_mapping`` do node.data.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-17 11:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "custom_node_definitions",
        sa.Column(
            "form_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Schema opcional de apresentacao do formulario. Shape: "
                "{ fields: [{ key, label?, help?, required?, hidden?, "
                "default_upstream? }] }. Nao altera semantica de execucao."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("custom_node_definitions", "form_schema")
