"""add full_name to users

Revision ID: a1b2c3d4e5f6
Revises: f3a9c2e871bd
Create Date: 2026-04-13 18:00:00.000000+00:00

Alterações:
  - users.full_name → nova coluna VARCHAR(255) NULL
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a9c2e871bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("full_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "full_name")
