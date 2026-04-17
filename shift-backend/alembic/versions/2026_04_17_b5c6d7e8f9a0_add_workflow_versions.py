"""add workflow_versions

Versoes imutaveis publicadas de um workflow, usadas como sub-workflows
pelo no ``call_workflow``. Cada linha e um snapshot da ``definition`` +
``io_schema`` (inputs/outputs declarados) no momento da publicacao.

Workflows podem ser invocados por outros via ``call_workflow``, com
pin em uma versao especifica (inteiro) ou na ultima publicada
(``"latest"``). A unique (workflow_id, version) garante monotonicidade.

Revision ID: b5c6d7e8f9aa
Revises: a4b5c6d7e8f9
Create Date: 2026-04-17 16:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "b5c6d7e8f9aa"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
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
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            comment="Numero sequencial da versao publicada (1-based).",
        ),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Snapshot imutavel dos nodes/edges no momento da publicacao.",
        ),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Lista de WorkflowParam declarando os inputs aceitos.",
        ),
        sa.Column(
            "output_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Lista de WorkflowParam declarando os outputs retornados.",
        ),
        sa.Column(
            "published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.UniqueConstraint(
            "workflow_id", "version", name="uq_workflow_versions_wf_version"
        ),
    )
    op.create_index(
        "ix_workflow_versions_workflow_id",
        "workflow_versions",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_versions_workflow_id", table_name="workflow_versions"
    )
    op.drop_table("workflow_versions")
