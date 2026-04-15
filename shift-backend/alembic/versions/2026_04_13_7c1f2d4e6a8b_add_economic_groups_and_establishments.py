"""add economic groups and establishments

Revision ID: 7c1f2d4e6a8b
Revises: c4a6b8d9e1f2, e1a4c7b9f210
Create Date: 2026-04-13 21:10:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c1f2d4e6a8b"
down_revision: Union[str, tuple[str, str], None] = ("c4a6b8d9e1f2", "e1a4c7b9f210")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "economic_group",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_economic_group_org_name"),
    )
    op.create_index(
        op.f("ix_economic_group_organization_id"),
        "economic_group",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "establishments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("economic_group_id", sa.UUID(), nullable=False),
        sa.Column("corporate_name", sa.String(length=255), nullable=False),
        sa.Column("trade_name", sa.String(length=255), nullable=True),
        sa.Column("cnpj", sa.String(length=14), nullable=False),
        sa.Column("erp_code", sa.Integer(), nullable=True),
        sa.Column("cnae", sa.String(length=20), nullable=False),
        sa.Column("state_registration", sa.String(length=40), nullable=True),
        sa.Column("cep", sa.String(length=8), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["economic_group_id"], ["economic_group.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cnpj", name="uq_establishment_cnpj"),
    )
    op.create_index(
        op.f("ix_establishments_cnpj"),
        "establishments",
        ["cnpj"],
        unique=False,
    )
    op.create_index(
        op.f("ix_establishments_economic_group_id"),
        "establishments",
        ["economic_group_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_establishments_economic_group_id"), table_name="establishments")
    op.drop_index(op.f("ix_establishments_cnpj"), table_name="establishments")
    op.drop_table("establishments")

    op.drop_index(op.f("ix_economic_group_organization_id"), table_name="economic_group")
    op.drop_table("economic_group")
