"""add webhook_test_captures

Buffer de curta duracao que armazena a ultima requisicao recebida em
cada par (workflow_id, node_id) pela URL de teste do no Webhook. A UI
(botao "Listen for test event") aguarda notificacao ou faz polling
para exibir o payload capturado.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-04-16 14:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "d1e2f3a4b5c6"
down_revision = ("c9d0e1f2a3b4", "f1a2b3c4d5e6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_test_captures",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "query_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("raw_body_b64", sa.Text(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workflow_id", "node_id", name="uq_webhook_test_workflow_node"
        ),
    )
    op.create_index(
        "ix_webhook_test_captures_workflow_id",
        "webhook_test_captures",
        ["workflow_id"],
    )
    op.create_index(
        "ix_webhook_test_captures_node_id",
        "webhook_test_captures",
        ["node_id"],
    )
    op.create_index(
        "ix_webhook_test_captures_expires_at",
        "webhook_test_captures",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_test_captures_expires_at",
        table_name="webhook_test_captures",
    )
    op.drop_index(
        "ix_webhook_test_captures_node_id",
        table_name="webhook_test_captures",
    )
    op.drop_index(
        "ix_webhook_test_captures_workflow_id",
        table_name="webhook_test_captures",
    )
    op.drop_table("webhook_test_captures")
