"""add platform agent tables

Revision ID: a9b8c7d6e5f4
Revises: d7e8f9a0b1cc
Create Date: 2026-04-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a9b8c7d6e5f4"
down_revision = "d7e8f9a0b1cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "initial_context",
            sa.dialects.postgresql.JSONB(),
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
    )
    op.create_index("ix_agent_threads_user_id", "agent_threads", ["user_id"])
    op.create_index("ix_agent_threads_workspace_id", "agent_threads", ["workspace_id"])
    op.create_index("ix_agent_threads_project_id", "agent_threads", ["project_id"])
    op.create_index("ix_agent_threads_status", "agent_threads", ["status"])

    op.create_table(
        "agent_messages",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "thread_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "tool_calls",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("tool_call_id", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_agent_messages_thread_id_created_at",
        "agent_messages",
        ["thread_id", "created_at"],
    )

    op.create_table(
        "agent_approvals",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "thread_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proposed_plan",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "decided_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_approvals_thread_id", "agent_approvals", ["thread_id"])
    op.create_index("ix_agent_approvals_status", "agent_approvals", ["status"])
    op.create_index("ix_agent_approvals_expires_at", "agent_approvals", ["expires_at"])

    op.create_table(
        "agent_audit_log",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "thread_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_threads.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_approvals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column(
            "tool_arguments",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column("tool_result_preview", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_audit_log_thread_id", "agent_audit_log", ["thread_id"])
    op.create_index("ix_agent_audit_log_user_id", "agent_audit_log", ["user_id"])
    op.create_index("ix_agent_audit_log_tool_name", "agent_audit_log", ["tool_name"])
    op.create_index("ix_agent_audit_log_created_at", "agent_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_audit_log_created_at", table_name="agent_audit_log")
    op.drop_index("ix_agent_audit_log_tool_name", table_name="agent_audit_log")
    op.drop_index("ix_agent_audit_log_user_id", table_name="agent_audit_log")
    op.drop_index("ix_agent_audit_log_thread_id", table_name="agent_audit_log")
    op.drop_table("agent_audit_log")

    op.drop_index("ix_agent_approvals_expires_at", table_name="agent_approvals")
    op.drop_index("ix_agent_approvals_status", table_name="agent_approvals")
    op.drop_index("ix_agent_approvals_thread_id", table_name="agent_approvals")
    op.drop_table("agent_approvals")

    op.drop_index(
        "ix_agent_messages_thread_id_created_at", table_name="agent_messages"
    )
    op.drop_table("agent_messages")

    op.drop_index("ix_agent_threads_status", table_name="agent_threads")
    op.drop_index("ix_agent_threads_project_id", table_name="agent_threads")
    op.drop_index("ix_agent_threads_workspace_id", table_name="agent_threads")
    op.drop_index("ix_agent_threads_user_id", table_name="agent_threads")
    op.drop_table("agent_threads")
