"""
Servico de linhas de dados dos modelos de entrada (InputModelRow).

Permite inserir, listar, atualizar e remover dados de referencia
armazenados internamente em um InputModel.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.input_model_row import InputModelRow


class InputModelRowService:
    """CRUD + bulk operations para linhas de um InputModel."""

    async def list_rows(
        self, db: AsyncSession, input_model_id: UUID
    ) -> tuple[list[InputModelRow], int]:
        """Lista rows com count em 1 query usando window function."""
        result = await db.execute(
            select(
                InputModelRow,
                func.count().over().label("total"),
            )
            .where(InputModelRow.input_model_id == input_model_id)
            .order_by(InputModelRow.row_order)
        )
        rows_with_total = result.all()
        if not rows_with_total:
            return [], 0
        total = rows_with_total[0][1]
        rows = [row[0] for row in rows_with_total]
        return rows, total

    async def add_row(
        self, db: AsyncSession, input_model_id: UUID, data: dict
    ) -> InputModelRow:
        # Get next row_order
        result = await db.execute(
            select(func.coalesce(func.max(InputModelRow.row_order), -1))
            .where(InputModelRow.input_model_id == input_model_id)
        )
        next_order = result.scalar_one() + 1

        row = InputModelRow(
            input_model_id=input_model_id,
            row_order=next_order,
            data=data,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def add_rows_bulk(
        self, db: AsyncSession, input_model_id: UUID, rows_data: list[dict]
    ) -> list[InputModelRow]:
        # Get next row_order
        result = await db.execute(
            select(func.coalesce(func.max(InputModelRow.row_order), -1))
            .where(InputModelRow.input_model_id == input_model_id)
        )
        next_order = result.scalar_one() + 1

        rows = []
        for i, data in enumerate(rows_data):
            row = InputModelRow(
                input_model_id=input_model_id,
                row_order=next_order + i,
                data=data,
            )
            db.add(row)
            rows.append(row)

        await db.flush()
        # Os campos gerados pelo server (id, created_at) ja estao disponiveis
        # apos flush com expire_on_commit=False — sem necessidade de refresh individual.
        return rows

    async def update_row(
        self, db: AsyncSession, row_id: UUID, data: dict
    ) -> InputModelRow | None:
        row = await db.get(InputModelRow, row_id)
        if row is None:
            return None
        row.data = data
        await db.flush()
        await db.refresh(row)
        return row

    async def delete_row(self, db: AsyncSession, row_id: UUID) -> bool:
        row = await db.get(InputModelRow, row_id)
        if row is None:
            return False
        await db.delete(row)
        await db.flush()
        return True

    async def clear_rows(self, db: AsyncSession, input_model_id: UUID) -> int:
        result = await db.execute(
            delete(InputModelRow).where(InputModelRow.input_model_id == input_model_id)
        )
        await db.flush()
        return result.rowcount


input_model_row_service = InputModelRowService()
