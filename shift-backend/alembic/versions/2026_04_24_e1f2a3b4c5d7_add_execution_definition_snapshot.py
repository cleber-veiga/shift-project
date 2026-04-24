"""add workflow_definition_snapshot to workflow_executions

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c6
Create Date: 2026-04-24

Adiciona duas colunas a ``workflow_executions`` (Sprint 4.1):

- ``workflow_definition_snapshot`` (JSONB, nullable) — copia da definicao
  do workflow (nodes + edges + config) no momento exato do disparo.
  Permite reconstruir o canvas como era executado mesmo apos edicoes futuras.

- ``definition_snapshot_hash`` (TEXT(64), nullable, indexed) — SHA-256 hex
  do snapshot, pre-computado pelo servico para comparacao rapida com a hash
  da definicao atual na listagem de execucoes (indicador de divergencia).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e1f2a3b4c5d7"
down_revision = "d0e1f2a3b4c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "workflow_definition_snapshot",
            JSONB,
            nullable=True,
            comment="Snapshot da definicao do workflow no momento do disparo.",
        ),
    )
    op.add_column(
        "workflow_executions",
        sa.Column(
            "definition_snapshot_hash",
            sa.String(64),
            nullable=True,
            comment="SHA-256 hex do snapshot para comparacao rapida.",
        ),
    )
    op.create_index(
        "ix_workflow_executions_snapshot_hash",
        "workflow_executions",
        ["definition_snapshot_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_executions_snapshot_hash", table_name="workflow_executions")
    op.drop_column("workflow_executions", "definition_snapshot_hash")
    op.drop_column("workflow_executions", "workflow_definition_snapshot")
