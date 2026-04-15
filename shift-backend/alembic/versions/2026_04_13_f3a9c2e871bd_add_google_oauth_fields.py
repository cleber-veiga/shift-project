"""add google oauth fields to users

Revision ID: f3a9c2e871bd
Revises: dae1d5d154ca
Create Date: 2026-04-13 12:00:00.000000+00:00

Alterações:
  - users.hashed_password  → nullable=True  (contas Google não têm senha local)
  - users.auth_provider    → nova coluna VARCHAR(50) NOT NULL DEFAULT 'local'
  - users.google_id        → nova coluna VARCHAR(255) UNIQUE NULL + índice
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a9c2e871bd'
down_revision: Union[str, None] = 'dae1d5d154ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tornar hashed_password nullable (usuários Google não têm senha local)
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.String(length=1024),
        nullable=True,
    )

    # 2. Adicionar coluna auth_provider com default 'local' para linhas existentes
    op.add_column(
        'users',
        sa.Column(
            'auth_provider',
            sa.String(length=50),
            nullable=False,
            server_default='local',
        ),
    )

    # 3. Adicionar coluna google_id (nullable, unique)
    op.add_column(
        'users',
        sa.Column('google_id', sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f('ix_users_google_id'),
        'users',
        ['google_id'],
        unique=True,
    )


def downgrade() -> None:
    # Desfaz na ordem inversa
    op.drop_index(op.f('ix_users_google_id'), table_name='users')
    op.drop_column('users', 'google_id')
    op.drop_column('users', 'auth_provider')

    # Restaura hashed_password como NOT NULL.
    # Atenção: isso falhará se existirem linhas com hashed_password IS NULL
    # (contas criadas via Google após o upgrade). Remova-as antes de fazer downgrade.
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.String(length=1024),
        nullable=False,
    )
