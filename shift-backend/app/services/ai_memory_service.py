"""
Servico de memoria do Assistente SQL.

Mantem um pool de queries que o usuario aplicou ao editor a partir do chat —
sao usadas como exemplos de estilo nas futuras conversas.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_chat_memory import AiChatMemory

# Quantas memorias sao injetadas no prompt
_INJECT_TOP_N = 5
# Limite maximo de memorias mantidas por (connection, user) — mais antigas sao podadas
_MAX_PER_USER_CONN = 50


def _normalize(query: str) -> str:
    """Normaliza SQL para hashing (remove comentarios, colapsa espacos)."""
    q = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    q = re.sub(r"--[^\n]*", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q.lower()


def _hash(query: str) -> str:
    return hashlib.sha256(_normalize(query).encode("utf-8")).hexdigest()


class AiMemoryService:
    """CRUD + poda de memorias do assistente."""

    async def record(
        self,
        db: AsyncSession,
        connection_id: UUID,
        user_id: UUID,
        query: str,
        description: str | None = None,
    ) -> AiChatMemory:
        """Cria ou atualiza a memoria. Dedup por hash normalizado."""
        query = (query or "").strip()
        if not query:
            raise ValueError("Query vazia.")

        qhash = _hash(query)

        stmt = sa.select(AiChatMemory).where(
            AiChatMemory.connection_id == connection_id,
            AiChatMemory.user_id == user_id,
            AiChatMemory.query_hash == qhash,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing is not None:
            # Re-toca a memoria — sobe na ordenacao por updated_at
            existing.query = query
            if description is not None:
                existing.description = description
            await db.flush()
            memory = existing
        else:
            memory = AiChatMemory(
                connection_id=connection_id,
                user_id=user_id,
                query=query,
                query_hash=qhash,
                description=description,
            )
            db.add(memory)
            await db.flush()

        await self._prune(db, connection_id, user_id)
        await db.commit()
        return memory

    async def list_recent(
        self,
        db: AsyncSession,
        connection_id: UUID,
        user_id: UUID,
        limit: int = _INJECT_TOP_N,
    ) -> list[dict[str, Any]]:
        """Lista as N memorias mais recentes para injecao no prompt."""
        stmt = (
            sa.select(AiChatMemory)
            .where(
                AiChatMemory.connection_id == connection_id,
                AiChatMemory.user_id == user_id,
            )
            .order_by(AiChatMemory.updated_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": str(m.id),
                "query": m.query,
                "description": m.description,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in rows
        ]

    async def delete(
        self,
        db: AsyncSession,
        memory_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Remove uma memoria (apenas se pertence ao usuario)."""
        stmt = sa.select(AiChatMemory).where(
            AiChatMemory.id == memory_id,
            AiChatMemory.user_id == user_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
        return True

    async def _prune(
        self,
        db: AsyncSession,
        connection_id: UUID,
        user_id: UUID,
    ) -> None:
        """Mantem apenas as N memorias mais recentes."""
        count_stmt = sa.select(sa.func.count(AiChatMemory.id)).where(
            AiChatMemory.connection_id == connection_id,
            AiChatMemory.user_id == user_id,
        )
        count = (await db.execute(count_stmt)).scalar_one()
        if count <= _MAX_PER_USER_CONN:
            return

        # Pega os IDs das mais antigas que devem ser removidas
        excess = count - _MAX_PER_USER_CONN
        old_ids_stmt = (
            sa.select(AiChatMemory.id)
            .where(
                AiChatMemory.connection_id == connection_id,
                AiChatMemory.user_id == user_id,
            )
            .order_by(AiChatMemory.updated_at.asc())
            .limit(excess)
        )
        old_ids = [row[0] for row in (await db.execute(old_ids_stmt)).all()]
        if old_ids:
            await db.execute(
                sa.delete(AiChatMemory).where(AiChatMemory.id.in_(old_ids))
            )


ai_memory_service = AiMemoryService()
