"""add shift_extract_cache table

Revision ID: f2a3b4c5d6e8
Revises: e1f2a3b4c5d7
Create Date: 2026-04-24

Cria a tabela ``shift_extract_cache`` para cache opcional de resultados
de nos de extracao (Sprint 4.4).

Cada linha armazena o result_json de um processador de extracao
(sql_database, csv_input, excel_input, api_input) identificado por
``cache_key`` (SHA-256 dos campos deterministas do no). Os arquivos DuckDB
referenciados em ``result_json`` ficam em SHIFT_EXTRACT_CACHE_DIR — um
diretorio persistente (nao /tmp).

Expiracao controlada por ``expires_at`` (TTL configuravel no no, default
5 minutos). Um job APScheduler (24h) faz a limpeza periodica.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f2a3b4c5d6e8"
down_revision = "e1f2a3b4c5d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_extract_cache",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "cache_key",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hex dos campos deterministas do no.",
        ),
        sa.Column(
            "node_type",
            sa.String(50),
            nullable=False,
            comment="Tipo do no que gerou o cache.",
        ),
        sa.Column(
            "result_json",
            JSONB,
            nullable=False,
            comment="Result dict do processador com caminhos DuckDB persistentes.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Timestamp de expiracao.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "hit_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Quantidade de cache hits.",
        ),
        sa.UniqueConstraint("cache_key", name="uq_extract_cache_key"),
    )
    op.create_index("ix_extract_cache_key", "shift_extract_cache", ["cache_key"])
    op.create_index("ix_extract_cache_expires_at", "shift_extract_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_extract_cache_expires_at", table_name="shift_extract_cache")
    op.drop_index("ix_extract_cache_key", table_name="shift_extract_cache")
    op.drop_table("shift_extract_cache")
