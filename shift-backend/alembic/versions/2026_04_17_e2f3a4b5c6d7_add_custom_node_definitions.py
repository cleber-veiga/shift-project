"""add custom_node_definitions

Cadastro de definicoes de "nos personalizados" (composite nodes): blueprints
reutilizaveis que encapsulam escrita transacional em multiplas tabelas
relacionadas de um sistema de destino (ex: NOTA + NOTAITEM + NOTAICMS).

O blueprint e serializado em JSONB e denormalizado no ``node.data`` do
workflow no momento da adicao do no ao canvas — garantindo imutabilidade
por snapshot (workflows antigos continuam funcionando se a definicao
for editada).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-17 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_node_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column(
            "category", sa.String(length=50), nullable=False, server_default="output"
        ),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("color", sa.String(length=50), nullable=True),
        sa.Column(
            "kind",
            sa.String(length=50),
            nullable=False,
            server_default="composite_insert",
            comment="Familia do nosso personalizado. Phase 1: apenas composite_insert.",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "blueprint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment=(
                "Contrato estruturado da composicao. Schema: tables[] com alias, "
                "table, role (header|child), parent_alias, fk_map, columns[] e "
                "returning[]. Validado em tempo de CRUD e no processor."
            ),
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "workspace_id IS NOT NULL OR project_id IS NOT NULL",
            name="ck_custom_node_owner_not_null",
        ),
        sa.CheckConstraint(
            "NOT (workspace_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_custom_node_single_owner",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "name",
            "version",
            name="uq_custom_node_scope_name_version",
        ),
    )
    op.create_index(
        "ix_custom_node_definitions_workspace_id",
        "custom_node_definitions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_custom_node_definitions_project_id",
        "custom_node_definitions",
        ["project_id"],
    )
    op.create_index(
        "ix_custom_node_definitions_created_by_id",
        "custom_node_definitions",
        ["created_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_custom_node_definitions_created_by_id",
        table_name="custom_node_definitions",
    )
    op.drop_index(
        "ix_custom_node_definitions_project_id",
        table_name="custom_node_definitions",
    )
    op.drop_index(
        "ix_custom_node_definitions_workspace_id",
        table_name="custom_node_definitions",
    )
    op.drop_table("custom_node_definitions")
