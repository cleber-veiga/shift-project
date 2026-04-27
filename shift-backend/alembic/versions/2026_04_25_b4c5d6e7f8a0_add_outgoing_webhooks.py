"""add outgoing webhook subscriptions / deliveries / dead-letters

Revision ID: b4c5d6e7f8a0
Revises: a3b4c5d6e7f9
Create Date: 2026-04-25

Cria a infra de webhooks de saida (Prompt 6.3):

- ``webhook_subscriptions``: registro do cliente (URL, eventos, secret HMAC).
- ``webhook_deliveries``: fila persistente de tentativas; tem indice composto
  (status, next_attempt_at) para o worker periodico fazer FOR UPDATE SKIP
  LOCKED eficiente.
- ``webhook_dead_letters``: entradas finalizadas como falha — preserva
  payload e detalhes da ultima tentativa para replay manual.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID


revision = "b4c5d6e7f8a0"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "workspace_id", UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("events", ARRAY(sa.String(64)), nullable=False),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "active", sa.Boolean,
            nullable=False, server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer, nullable=True),
    )
    op.create_index(
        "ix_webhook_subscriptions_workspace_id",
        "webhook_subscriptions", ["workspace_id"],
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id", UUID(as_uuid=True),
            sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="pending",
        ),
        sa.Column(
            "attempt_count", sa.SmallInteger,
            nullable=False, server_default="0",
        ),
        sa.Column(
            "max_attempts", sa.SmallInteger,
            nullable=False, server_default="6",
        ),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("last_status_code", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("execution_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_subscription_id",
        "webhook_deliveries", ["subscription_id"],
    )
    op.create_index(
        "ix_webhook_deliveries_status_next_attempt_at",
        "webhook_deliveries", ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_webhook_deliveries_execution_id",
        "webhook_deliveries", ["execution_id"],
    )

    op.create_table(
        "webhook_dead_letters",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id", UUID(as_uuid=True),
            sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "delivery_id", UUID(as_uuid=True),
            sa.ForeignKey("webhook_deliveries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("last_status_code", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "attempt_count", sa.SmallInteger,
            nullable=False, server_default="0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_webhook_dead_letters_subscription_id",
        "webhook_dead_letters", ["subscription_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_dead_letters_subscription_id",
        table_name="webhook_dead_letters",
    )
    op.drop_table("webhook_dead_letters")

    op.drop_index(
        "ix_webhook_deliveries_execution_id",
        table_name="webhook_deliveries",
    )
    op.drop_index(
        "ix_webhook_deliveries_status_next_attempt_at",
        table_name="webhook_deliveries",
    )
    op.drop_index(
        "ix_webhook_deliveries_subscription_id",
        table_name="webhook_deliveries",
    )
    op.drop_table("webhook_deliveries")

    op.drop_index(
        "ix_webhook_subscriptions_workspace_id",
        table_name="webhook_subscriptions",
    )
    op.drop_table("webhook_subscriptions")
