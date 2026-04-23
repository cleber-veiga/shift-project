"""add workflow_definition_events (mergepoint)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0, ba1c2d3e4f5a
Create Date: 2026-04-22

Observacao: esta migration atua como mergepoint das duas heads que ficaram
divergentes apos o hotfix de audit_log_metadata (ba1c2d3e4f5a). A cadeia de
agent_api_keys foi criada referenciando o hash do filename (b1c2d3e4f5a6)
em vez da revision id real (ba1c2d3e4f5a), deixando ba1c2d3e4f5a como head
paralela. Aqui unificamos as duas pontas para que `alembic upgrade head`
volte a funcionar com uma unica head.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f6a7b8c9d0e1"
down_revision = ("e5f6a7b8c9d0", "ba1c2d3e4f5a")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A sequence e criada explicitamente: `sa.Sequence(...)` no Column NAO
    # emite CREATE SEQUENCE no Alembic (diferente de DDL puro do SQLAlchemy).
    op.execute("CREATE SEQUENCE IF NOT EXISTS workflow_definition_events_seq_seq")

    op.create_table(
        "workflow_definition_events",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "workflow_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("client_mutation_id", sa.String(255), nullable=True),
        sa.Column(
            "seq",
            sa.BigInteger,
            nullable=False,
            unique=True,
            server_default=sa.text("nextval('workflow_definition_events_seq_seq')"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "ALTER SEQUENCE workflow_definition_events_seq_seq "
        "OWNED BY workflow_definition_events.seq"
    )
    op.create_index(
        "ix_wf_def_events_wf_seq",
        "workflow_definition_events",
        ["workflow_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_wf_def_events_wf_seq", "workflow_definition_events")
    op.drop_table("workflow_definition_events")
    op.execute("DROP SEQUENCE IF EXISTS workflow_definition_events_seq_seq")
