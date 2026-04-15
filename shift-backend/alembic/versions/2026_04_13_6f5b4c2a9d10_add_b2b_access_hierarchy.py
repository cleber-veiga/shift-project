"""add b2b access hierarchy

Revision ID: 6f5b4c2a9d10
Revises: f3a9c2e871bd
Create Date: 2026-04-13 13:30:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f5b4c2a9d10"
down_revision: Union[str, None] = "f3a9c2e871bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


organization_role = sa.Enum(
    "OWNER",
    "MANAGER",
    "MEMBER",
    "GUEST",
    name="organization_role",
    native_enum=False,
)
workspace_role = sa.Enum(
    "MANAGER",
    "CONSULTANT",
    "VIEWER",
    name="workspace_role",
    native_enum=False,
)
project_role = sa.Enum(
    "EDITOR",
    "CLIENT",
    name="project_role",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("billing_email", sa.String(length=320), nullable=True),
        sa.Column("legacy_workspace_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        "uq_organizations_legacy_workspace_id",
        "organizations",
        ["legacy_workspace_id"],
    )

    op.add_column("workspaces", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_workspaces_organization_id"), "workspaces", ["organization_id"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_workspace_id"), "projects", ["workspace_id"], unique=False)

    op.create_table(
        "organization_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", organization_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )
    op.create_index(op.f("ix_organization_members_organization_id"), "organization_members", ["organization_id"], unique=False)
    op.create_index(op.f("ix_organization_members_user_id"), "organization_members", ["user_id"], unique=False)

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", workspace_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_index(op.f("ix_workspace_members_workspace_id"), "workspace_members", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_workspace_members_user_id"), "workspace_members", ["user_id"], unique=False)

    op.create_table(
        "project_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", project_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )
    op.create_index(op.f("ix_project_members_project_id"), "project_members", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_members_user_id"), "project_members", ["user_id"], unique=False)

    op.add_column("workflows", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_workflows_project_id"), "workflows", ["project_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO organizations (id, name, billing_email, legacy_workspace_id, created_at)
            SELECT
                gen_random_uuid(),
                w.name,
                u.email,
                w.id,
                w.created_at
            FROM workspaces w
            LEFT JOIN LATERAL (
                SELECT email
                FROM users
                WHERE workspace_id = w.id
                ORDER BY created_at ASC, email ASC
                LIMIT 1
            ) u ON TRUE
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE workspaces w
            SET organization_id = o.id
            FROM organizations o
            WHERE o.legacy_workspace_id = w.id
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO projects (id, workspace_id, name, description, created_at)
            SELECT
                gen_random_uuid(),
                w.id,
                'Default Project',
                'Projeto default criado na migracao da hierarquia B2B.',
                w.created_at
            FROM workspaces w
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO organization_members (id, organization_id, user_id, role, created_at)
            SELECT
                gen_random_uuid(),
                o.id,
                u.id,
                'OWNER',
                now()
            FROM users u
            JOIN organizations o
              ON o.legacy_workspace_id = u.workspace_id
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO workspace_members (id, workspace_id, user_id, role, created_at)
            SELECT
                gen_random_uuid(),
                u.workspace_id,
                u.id,
                'MANAGER',
                now()
            FROM users u
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE workflows wf
            SET project_id = p.id
            FROM projects p
            WHERE p.workspace_id = wf.workspace_id
            """
        )
    )

    op.alter_column("workspaces", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_workspaces_organization_id",
        "workspaces",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column("workflows", "project_id", nullable=False)
    op.create_foreign_key(
        "fk_workflows_project_id",
        "workflows",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("users_workspace_id_fkey", "users", type_="foreignkey")
    op.drop_constraint("workflows_workspace_id_fkey", "workflows", type_="foreignkey")
    op.drop_column("users", "workspace_id")
    op.drop_column("workflows", "workspace_id")
    op.drop_constraint("uq_organizations_legacy_workspace_id", "organizations", type_="unique")
    op.drop_column("organizations", "legacy_workspace_id")


def downgrade() -> None:
    op.add_column("users", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("workflows", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "users_workspace_id_fkey",
        "users",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    op.create_foreign_key(
        "workflows_workspace_id_fkey",
        "workflows",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )

    op.execute(
        sa.text(
            """
            WITH ranked_members AS (
                SELECT
                    wm.user_id,
                    wm.workspace_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY wm.user_id
                        ORDER BY CASE wm.role
                            WHEN 'MANAGER' THEN 1
                            WHEN 'CONSULTANT' THEN 2
                            ELSE 3
                        END,
                        wm.created_at
                    ) AS row_num
                FROM workspace_members wm
            )
            UPDATE users u
            SET workspace_id = rm.workspace_id
            FROM ranked_members rm
            WHERE rm.user_id = u.id
              AND rm.row_num = 1
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE workflows wf
            SET workspace_id = p.workspace_id
            FROM projects p
            WHERE p.id = wf.project_id
            """
        )
    )

    op.alter_column("users", "workspace_id", nullable=False)
    op.alter_column("workflows", "workspace_id", nullable=False)

    op.drop_constraint("fk_workflows_project_id", "workflows", type_="foreignkey")
    op.drop_index(op.f("ix_workflows_project_id"), table_name="workflows")
    op.drop_column("workflows", "project_id")

    op.drop_index(op.f("ix_project_members_user_id"), table_name="project_members")
    op.drop_index(op.f("ix_project_members_project_id"), table_name="project_members")
    op.drop_table("project_members")

    op.drop_index(op.f("ix_workspace_members_user_id"), table_name="workspace_members")
    op.drop_index(op.f("ix_workspace_members_workspace_id"), table_name="workspace_members")
    op.drop_table("workspace_members")

    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_organization_id"), table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index(op.f("ix_projects_workspace_id"), table_name="projects")
    op.drop_table("projects")

    op.drop_constraint("fk_workspaces_organization_id", "workspaces", type_="foreignkey")
    op.drop_index(op.f("ix_workspaces_organization_id"), table_name="workspaces")
    op.drop_column("workspaces", "organization_id")

    op.drop_table("organizations")
