"""add invitations table

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column(
            "scope",
            sa.String(32),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("invited_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by_id"], ["users.id"]),
        sa.CheckConstraint(
            """
            (scope = 'ORGANIZATION' AND organization_id IS NOT NULL
                AND workspace_id IS NULL AND project_id IS NULL)
            OR
            (scope = 'WORKSPACE' AND workspace_id IS NOT NULL
                AND project_id IS NULL)
            OR
            (scope = 'PROJECT' AND project_id IS NOT NULL)
            """,
            name="ck_invitation_scope_ids",
        ),
    )

    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_token", "invitations", ["token"], unique=True)
    op.create_index(
        "ix_invitations_organization_id", "invitations", ["organization_id"]
    )
    op.create_index("ix_invitations_workspace_id", "invitations", ["workspace_id"])
    op.create_index("ix_invitations_project_id", "invitations", ["project_id"])
    op.create_index("ix_invitations_invited_by_id", "invitations", ["invited_by_id"])
    op.create_index(
        "ix_invitations_email_status", "invitations", ["email", "status"]
    )

    # Unique partial index: previne duplicata de PENDING por email+scope+scope_id
    op.execute(
        """
        CREATE UNIQUE INDEX uq_pending_invitation
        ON invitations (
            email, scope,
            COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'),
            COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'),
            COALESCE(project_id, '00000000-0000-0000-0000-000000000000')
        )
        WHERE status = 'PENDING'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pending_invitation")
    op.drop_index("ix_invitations_email_status", table_name="invitations")
    op.drop_index("ix_invitations_invited_by_id", table_name="invitations")
    op.drop_index("ix_invitations_project_id", table_name="invitations")
    op.drop_index("ix_invitations_workspace_id", table_name="invitations")
    op.drop_index("ix_invitations_organization_id", table_name="invitations")
    op.drop_index("ix_invitations_token", table_name="invitations")
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_table("invitations")
