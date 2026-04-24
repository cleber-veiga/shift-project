"""
Modelo ORM: ExtractCache — cache persistente de resultados de nos de extracao.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ExtractCache(Base):
    """Entrada de cache para output de um no de extracao (sql_database, csv_input, etc.).

    A chave de cache e um SHA-256 do conteudo determinista do no (connection_id,
    query normalizada, parametros, chunk_size). O ``result_json`` espelha o
    dict retornado pelo processador, com caminhos DuckDB atualizados para o
    diretorio persistente de cache (SHIFT_EXTRACT_CACHE_DIR).

    Em cache hit, o runner copia o arquivo DuckDB para o diretorio temporario
    da execucao corrente e devolve o result_json com os caminhos atualizados,
    emitindo ``is_cache_hit=True`` no evento SSE.
    """

    __tablename__ = "shift_extract_cache"

    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_extract_cache_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    cache_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA-256 hex dos campos deterministas do no.",
    )
    node_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Tipo do no que gerou o cache (sql_database, csv_input, etc.).",
    )
    result_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Result dict do processador com caminhos DuckDB apontando para o cache dir.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Timestamp de expiracao do cache.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    hit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0,
        comment="Quantidade de vezes que este cache foi utilizado.",
    )
