"""merge full_name and workflow_templates

Revision ID: 9db3ffc3c2c4
Revises: a1b2c3d4e5f6, b7e8f9a0c1d2
Create Date: 2026-04-13 17:01:51.378207+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores da revisão usados pelo Alembic
revision: str = '9db3ffc3c2c4'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'b7e8f9a0c1d2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
