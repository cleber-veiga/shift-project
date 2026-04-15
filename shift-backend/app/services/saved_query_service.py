"""
Serviço para consultas SQL salvas — CRUD com validação SQL.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_query import SavedQuery
from app.services.playground_service import validate_query


class SavedQueryService:
    """CRUD de consultas SQL salvas, vinculadas a player + database_type."""

    async def create(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        player_id: UUID,
        database_type: str,
        name: str,
        description: str | None,
        query: str,
        created_by_id: UUID | None,
    ) -> SavedQuery:
        error = validate_query(query)
        if error:
            raise ValueError(error)

        obj = SavedQuery(
            workspace_id=workspace_id,
            player_id=player_id,
            database_type=database_type,
            name=name,
            description=description,
            query=query,
            created_by_id=created_by_id,
        )
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    async def list_for_connection(
        self,
        db: AsyncSession,
        player_id: UUID,
        database_type: str,
    ) -> list[SavedQuery]:
        """Lista todas as queries salvas para um concorrente + tipo de banco."""
        stmt = (
            sa.select(SavedQuery)
            .where(
                SavedQuery.player_id == player_id,
                SavedQuery.database_type == database_type,
            )
            .order_by(SavedQuery.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, db: AsyncSession, query_id: UUID) -> SavedQuery | None:
        result = await db.execute(
            sa.select(SavedQuery).where(SavedQuery.id == query_id)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        query_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        query: str | None = None,
    ) -> SavedQuery:
        obj = await self.get(db, query_id)
        if obj is None:
            raise ValueError("Consulta salva não encontrada.")

        if query is not None:
            error = validate_query(query)
            if error:
                raise ValueError(error)
            obj.query = query

        if name is not None:
            obj.name = name

        # description=None means "don't change", empty string means "clear"
        if description is not None:
            obj.description = description if description else None

        await db.commit()
        await db.refresh(obj)
        return obj

    async def delete(self, db: AsyncSession, query_id: UUID) -> None:
        obj = await self.get(db, query_id)
        if obj is None:
            raise ValueError("Consulta salva não encontrada.")
        await db.delete(obj)
        await db.commit()


saved_query_service = SavedQueryService()
