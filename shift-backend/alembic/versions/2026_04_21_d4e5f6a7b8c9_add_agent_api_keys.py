"""add agent_api_keys table

Revision ID: d4e5f6a7b8c9
Revises: b1c2d3e4f5a6
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d4e5f6a7b8c9"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_api_keys",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column(
            "workspace_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("max_workspace_role", sa.Text(), nullable=False),
        sa.Column("max_project_role", sa.Text(), nullable=True),
        sa.Column(
            "allowed_tools",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "require_human_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "usage_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("key_hash", name="uq_agent_api_key_hash"),
    )
    op.create_index(
        "ix_agent_api_keys_prefix", "agent_api_keys", ["prefix"]
    )
    op.create_index(
        "ix_agent_api_keys_workspace_id", "agent_api_keys", ["workspace_id"]
    )
    op.create_index(
        "ix_agent_api_keys_project_id", "agent_api_keys", ["project_id"]
    )
    op.create_index(
        "ix_agent_api_keys_workspace_revoked",
        "agent_api_keys",
        ["workspace_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_api_keys_workspace_revoked", table_name="agent_api_keys"
    )
    op.drop_index("ix_agent_api_keys_project_id", table_name="agent_api_keys")
    op.drop_index("ix_agent_api_keys_workspace_id", table_name="agent_api_keys")
    op.drop_index("ix_agent_api_keys_prefix", table_name="agent_api_keys")
    op.drop_table("agent_api_keys")
