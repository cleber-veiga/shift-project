"""repair connections table

Revision ID: 03902dfb62c4
Revises: 9db3ffc3c2c4
Create Date: 2026-04-13 18:14:48.839062+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identificadores da revisão usados pelo Alembic
revision: str = '03902dfb62c4'
down_revision: Union[str, None] = '9db3ffc3c2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: em bancos legados a tabela `connections` pode ter sido
    # perdida e precisa ser recriada; em bancos novos ela já foi criada pela
    # migração `dae1d5d154ca_add_connections_table` e nada precisa ser feito.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'connections' not in existing_tables:
        op.create_table('connections',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('database', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('password', sa.String(length=1024), nullable=False),
        sa.Column('extra_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('connections')}
    if 'ix_connections_workspace_id' not in existing_indexes:
        op.create_index(op.f('ix_connections_workspace_id'), 'connections', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_connections_workspace_id'), table_name='connections')
    op.drop_table('connections')
