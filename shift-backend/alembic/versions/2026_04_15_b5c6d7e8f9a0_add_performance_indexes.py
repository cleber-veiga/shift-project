"""add performance indexes

Revision ID: b5c6d7e8f9a0
Revises: a409361ac779
Create Date: 2026-04-15
"""
from __future__ import annotations

from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "a409361ac779"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Indices compostos para membership lookups (usados em auth e listagens) ---
    op.create_index(
        "ix_organization_members_user_org",
        "organization_members",
        ["user_id", "organization_id"],
    )
    op.create_index(
        "ix_workspace_members_user_ws",
        "workspace_members",
        ["user_id", "workspace_id"],
    )
    op.create_index(
        "ix_project_members_user_proj",
        "project_members",
        ["user_id", "project_id"],
    )

    # --- Indices para colunas usadas em ORDER BY ---
    op.create_index("ix_organizations_name", "organizations", ["name"])
    op.create_index("ix_workspaces_name", "workspaces", ["name"])
    op.create_index("ix_projects_name", "projects", ["name"])
    op.create_index("ix_connections_name", "connections", ["name"])
    op.create_index("ix_workspace_players_name", "workspace_players", ["name"])
    op.create_index("ix_workflows_name", "workflows", ["name"])

    # --- Indice composto para filtro de workflows template/published ---
    op.create_index(
        "ix_workflows_ws_template_published",
        "workflows",
        ["workspace_id", "is_template", "is_published"],
    )

    # --- Indice para workflow_executions por workflow ---
    op.create_index(
        "ix_workflow_executions_workflow_id",
        "workflow_executions",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_executions_workflow_id", table_name="workflow_executions")
    op.drop_index("ix_workflows_ws_template_published", table_name="workflows")
    op.drop_index("ix_workflows_name", table_name="workflows")
    op.drop_index("ix_workspace_players_name", table_name="workspace_players")
    op.drop_index("ix_connections_name", table_name="connections")
    op.drop_index("ix_projects_name", table_name="projects")
    op.drop_index("ix_workspaces_name", table_name="workspaces")
    op.drop_index("ix_organizations_name", table_name="organizations")
    op.drop_index("ix_project_members_user_proj", table_name="project_members")
    op.drop_index("ix_workspace_members_user_ws", table_name="workspace_members")
    op.drop_index("ix_organization_members_user_org", table_name="organization_members")
