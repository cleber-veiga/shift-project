"""add trace_context column to webhook_deliveries (Task 3, hardening 6.2/6.3)

Revision ID: c5d6e7f8a0b1
Revises: b4c5d6e7f8a0
Create Date: 2026-04-25

Permite propagar W3C Trace Context (``traceparent`` / ``tracestate``) do
span da execucao -> worker do dispatch (cross-boundary). Sem esta coluna,
o span de ``webhook.dispatch`` ficaria orfao quando o worker rodasse num
processo/loop diferente do que enfileirou.

Coluna nullable porque deliveries antigas / modo dev sem tracing nao tem
contexto. Pequena (poucas dezenas de bytes por linha de JSON) — sem custo
relevante de armazenamento.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "c5d6e7f8a0b1"
down_revision = "b4c5d6e7f8a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column(
            "trace_context",
            JSONB,
            nullable=True,
            comment=(
                "W3C Trace Context (traceparent / tracestate) capturado no "
                "enqueue para propagacao cross-boundary. NULL = sem trace."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("webhook_deliveries", "trace_context")
