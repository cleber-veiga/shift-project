"""Endpoints de listagem e reprocessamento de dead-letters."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from app.schemas.dead_letter import DeadLetterListResponse, DeadLetterRetryResponse
from app.services.dead_letter_service import dead_letter_service


router = APIRouter(prefix="/dead-letters", tags=["dead-letters"])


@router.get("", response_model=DeadLetterListResponse)
async def list_dead_letters(
    workspace_id: UUID = Query(..., description="Workspace usado para autorizacao."),
    workflow_id: UUID | None = Query(None),
    execution_id: UUID | None = Query(None),
    include_resolved: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> DeadLetterListResponse:
    _ = workspace_id
    items, total = await dead_letter_service.list_entries(
        db,
        workflow_id=workflow_id,
        execution_id=execution_id,
        include_resolved=include_resolved,
        page=page,
        size=size,
    )
    return DeadLetterListResponse(items=items, total=total, page=page, size=size)


@router.post(
    "/{dead_letter_id}/retry",
    response_model=DeadLetterRetryResponse,
    status_code=status.HTTP_200_OK,
)
async def retry_dead_letter(
    dead_letter_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> DeadLetterRetryResponse:
    try:
        result = await dead_letter_service.retry_entry(
            db,
            dead_letter_id=dead_letter_id,
        )
        return DeadLetterRetryResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
