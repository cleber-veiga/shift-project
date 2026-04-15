"""
Endpoints REST para gerenciamento de dados (linhas) dos modelos de entrada.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import require_permission
from app.models import User
from app.schemas.input_model import (
    InputModelRowBulkCreate,
    InputModelRowCreate,
    InputModelRowResponse,
    InputModelRowsResponse,
)
from app.services.input_model_service import input_model_service
from app.services.input_model_row_service import input_model_row_service

router = APIRouter(tags=["input-model-rows"])


# ─── List rows ───────────────────────────────────────────────────────────────

@router.get(
    "/input-models/{input_model_id}/rows",
    response_model=InputModelRowsResponse,
)
async def list_rows(
    input_model_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> InputModelRowsResponse:
    """Lista todas as linhas de dados de um modelo de entrada."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")

    rows, total = await input_model_row_service.list_rows(db, input_model_id)
    return InputModelRowsResponse(total=total, rows=rows)


# ─── Add single row ─────────────────────────────────────────────────────────

@router.post(
    "/input-models/{input_model_id}/rows",
    response_model=InputModelRowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_row(
    input_model_id: UUID,
    data: InputModelRowCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> InputModelRowResponse:
    """Adiciona uma linha de dados ao modelo de entrada."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")

    row = await input_model_row_service.add_row(db, input_model_id, data.data)
    return row


# ─── Bulk add rows ──────────────────────────────────────────────────────────

@router.post(
    "/input-models/{input_model_id}/rows/bulk",
    response_model=InputModelRowsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_rows_bulk(
    input_model_id: UUID,
    payload: InputModelRowBulkCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> InputModelRowsResponse:
    """Adiciona multiplas linhas de dados em lote."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")

    rows = await input_model_row_service.add_rows_bulk(db, input_model_id, payload.rows)
    return InputModelRowsResponse(total=len(rows), rows=rows)


# ─── Update row ──────────────────────────────────────────────────────────────

@router.put(
    "/input-model-rows/{row_id}",
    response_model=InputModelRowResponse,
)
async def update_row(
    row_id: UUID,
    data: InputModelRowCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> InputModelRowResponse:
    """Atualiza os dados de uma linha."""
    row = await input_model_row_service.update_row(db, row_id, data.data)
    if row is None:
        raise HTTPException(status_code=404, detail="Linha nao encontrada.")
    return row


# ─── Delete row ──────────────────────────────────────────────────────────────

@router.delete(
    "/input-model-rows/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_row(
    row_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> None:
    """Remove uma linha de dados."""
    deleted = await input_model_row_service.delete_row(db, row_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Linha nao encontrada.")


# ─── Clear all rows ─────────────────────────────────────────────────────────

@router.delete(
    "/input-models/{input_model_id}/rows",
    status_code=status.HTTP_200_OK,
)
async def clear_rows(
    input_model_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> dict:
    """Remove todas as linhas de dados de um modelo."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")

    deleted_count = await input_model_row_service.clear_rows(db, input_model_id)
    return {"deleted": deleted_count}
