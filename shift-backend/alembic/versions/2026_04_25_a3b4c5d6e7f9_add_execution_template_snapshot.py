"""add immutable template snapshot to workflow_executions

Revision ID: a3b4c5d6e7f9
Revises: f2a3b4c5d6e8
Create Date: 2026-04-25

Substitui o snapshot da Sprint 4.1 (``workflow_definition_snapshot`` /
``definition_snapshot_hash``) por um snapshot imutavel, sanitizado e
obrigatorio que serve de audit trail e habilita ``replay`` deterministico.

Colunas novas:
- ``template_snapshot`` (JSONB, NOT NULL) — definicao renderizada pos-Jinja
  com valores de variaveis do tipo ``secret`` substituidos por ``<REDACTED>``.
- ``template_version`` (VARCHAR(64), indexed) — SHA-256 hex do snapshot,
  determinastico e usado para detectar divergencia da definicao atual.
- ``rendered_at`` (TIMESTAMPTZ, NOT NULL) — timestamp do render.

Imutabilidade: trigger ``trg_workflow_executions_snapshot_immutable``
bloqueia UPDATEs que modifiquem qualquer dos tres campos apos a criacao
da linha.

Backfill: linhas existentes recebem o snapshot antigo (ja persistido) e
``rendered_at = COALESCE(started_at, now())``. Linhas sem snapshot antigo
recebem ``{}`` + hash determinastico desse vazio.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a3b4c5d6e7f9"
down_revision = "f2a3b4c5d6e8"
branch_labels = None
depends_on = None


_HASH_OF_EMPTY_SNAPSHOT = (
    # SHA-256 de json.dumps({}, sort_keys=True) -> "{}"
    "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)


def upgrade() -> None:
    # Adiciona as colunas nullable para permitir backfill. NOT NULL e aplicado
    # depois que as linhas existentes sao preenchidas.
    op.add_column(
        "workflow_executions",
        sa.Column(
            "template_snapshot",
            JSONB,
            nullable=True,
            comment="Definicao do workflow renderizada e sanitizada (sem secrets).",
        ),
    )
    op.add_column(
        "workflow_executions",
        sa.Column(
            "template_version",
            sa.String(64),
            nullable=True,
            comment="SHA-256 hex do template_snapshot.",
        ),
    )
    op.add_column(
        "workflow_executions",
        sa.Column(
            "rendered_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp do render do template (audit trail).",
        ),
    )

    # Backfill: aproveita o snapshot/hash antigos quando existirem.
    op.execute(
        sa.text(
            """
            UPDATE workflow_executions
            SET
                template_snapshot = COALESCE(workflow_definition_snapshot, '{}'::jsonb),
                template_version = COALESCE(definition_snapshot_hash, :empty_hash),
                rendered_at = COALESCE(started_at, now())
            WHERE template_snapshot IS NULL
            """
        ).bindparams(empty_hash=_HASH_OF_EMPTY_SNAPSHOT)
    )

    op.alter_column("workflow_executions", "template_snapshot", nullable=False)
    op.alter_column("workflow_executions", "rendered_at", nullable=False)

    # Substitui o indice antigo do hash pelo novo da template_version.
    op.drop_index(
        "ix_workflow_executions_snapshot_hash",
        table_name="workflow_executions",
    )
    op.create_index(
        "ix_workflow_executions_template_version",
        "workflow_executions",
        ["template_version"],
    )

    # Remove as colunas legadas Sprint 4.1.
    op.drop_column("workflow_executions", "definition_snapshot_hash")
    op.drop_column("workflow_executions", "workflow_definition_snapshot")

    # Trigger de imutabilidade: rejeita UPDATEs que tentem alterar qualquer
    # uma das tres colunas do snapshot apos a criacao da linha. INSERTs sao
    # liberados normalmente porque o trigger so dispara em UPDATE.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION fn_workflow_executions_snapshot_immutable()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.template_snapshot IS DISTINCT FROM OLD.template_snapshot THEN
                    RAISE EXCEPTION 'workflow_executions.template_snapshot is immutable (execution_id=%)', OLD.id;
                END IF;
                IF NEW.template_version IS DISTINCT FROM OLD.template_version THEN
                    RAISE EXCEPTION 'workflow_executions.template_version is immutable (execution_id=%)', OLD.id;
                END IF;
                IF NEW.rendered_at IS DISTINCT FROM OLD.rendered_at THEN
                    RAISE EXCEPTION 'workflow_executions.rendered_at is immutable (execution_id=%)', OLD.id;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_workflow_executions_snapshot_immutable
            BEFORE UPDATE ON workflow_executions
            FOR EACH ROW
            EXECUTE FUNCTION fn_workflow_executions_snapshot_immutable();
            """
        )
    )


def downgrade() -> None:
    # Reverte trigger primeiro para liberar UPDATEs durante o backfill reverso.
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_workflow_executions_snapshot_immutable "
            "ON workflow_executions"
        )
    )
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS fn_workflow_executions_snapshot_immutable()")
    )

    # Recria as colunas legadas (nullable, como no schema original).
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

    # Backfill reverso a partir das colunas novas.
    op.execute(
        sa.text(
            """
            UPDATE workflow_executions
            SET
                workflow_definition_snapshot = template_snapshot,
                definition_snapshot_hash = template_version
            """
        )
    )

    op.drop_index(
        "ix_workflow_executions_template_version",
        table_name="workflow_executions",
    )
    op.create_index(
        "ix_workflow_executions_snapshot_hash",
        "workflow_executions",
        ["definition_snapshot_hash"],
    )

    op.drop_column("workflow_executions", "rendered_at")
    op.drop_column("workflow_executions", "template_version")
    op.drop_column("workflow_executions", "template_snapshot")
