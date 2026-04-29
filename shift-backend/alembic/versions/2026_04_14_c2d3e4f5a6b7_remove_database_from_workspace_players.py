"""Remove database column from workspace_players.

A coluna foi adicionada por engano na migration anterior.
Concorrentes armazenam apenas nome e tipo de banco — as informações
de conexão ficam na tabela connections.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-14
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: a coluna `database` só existe em bancos legados onde a
    # migração `e1a4c7b9f210` (numa versão anterior) chegou a criá-la. Em
    # bancos novos a versão atual de `e1a4c7b9f210` já nasce sem ela.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("workspace_players")}
    if "database" in columns:
        op.drop_column("workspace_players", "database")


def downgrade() -> None:
    op.add_column(
        "workspace_players",
        sa.Column("database", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("workspace_players", "database", server_default=None)
