"""add connections table

Revision ID: dae1d5d154ca
Revises: 1db69e241e7a
Create Date: 2026-04-13 11:32:47.973482+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Identificadores da revisão usados pelo Alembic
revision: str = 'dae1d5d154ca'
down_revision: Union[str, None] = '1db69e241e7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'connections',
        sa.Column(
            'id',
            sa.UUID(),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('database', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        # Senha armazenada como token Fernet (ciphertext em base64-url).
        # O TypeDecorator EncryptedString não altera o tipo físico da coluna.
        sa.Column('password', sa.String(length=1024), nullable=False),
        sa.Column(
            'extra_params',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_connections_workspace_id'),
        'connections',
        ['workspace_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_connections_workspace_id'), table_name='connections')
    op.drop_table('connections')
