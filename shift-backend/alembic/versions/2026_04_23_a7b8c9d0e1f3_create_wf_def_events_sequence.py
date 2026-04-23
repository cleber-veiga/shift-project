"""create workflow_definition_events_seq_seq sequence (hotfix)

Revision ID: a7b8c9d0e1f3
Revises: f6a7b8c9d0e1
Create Date: 2026-04-23

Hotfix: a migration f6a7b8c9d0e1 declarou `sa.Sequence(...)` na coluna `seq`
de `workflow_definition_events`, mas o Alembic nao emite CREATE SEQUENCE
implicitamente a partir desse atributo — a sequence ficou ausente no banco,
quebrando INSERTs com "relation workflow_definition_events_seq_seq does not
exist". Esta migration cria a sequence (idempotente) e anexa o default
correto a coluna seq.
"""

from __future__ import annotations

from alembic import op

revision = "a7b8c9d0e1f3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: se alguem ja criou manualmente, nao refaz.
    op.execute("CREATE SEQUENCE IF NOT EXISTS workflow_definition_events_seq_seq")
    # Faz a sequence "pertencer" a coluna (drop em cascata se a coluna/tabela cair).
    op.execute(
        "ALTER SEQUENCE workflow_definition_events_seq_seq "
        "OWNED BY workflow_definition_events.seq"
    )
    # Seta como default da coluna para INSERTs futuros que nao passem seq explicitamente.
    op.execute(
        "ALTER TABLE workflow_definition_events "
        "ALTER COLUMN seq SET DEFAULT nextval('workflow_definition_events_seq_seq')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_definition_events ALTER COLUMN seq DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS workflow_definition_events_seq_seq")
