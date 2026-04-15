"""
Endpoints REST para gerenciamento de modelos de entrada (Input Models).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import require_permission
from app.models import User
from app.schemas.input_model import (
    InputModelCreate,
    InputModelResponse,
    InputModelUpdate,
    ValidationResult,
)
from app.services.input_model_service import input_model_service

router = APIRouter(tags=["input-models"])


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/input-models",
    response_model=list[InputModelResponse],
)
async def list_input_models(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[InputModelResponse]:
    """Lista todos os modelos de entrada do workspace."""
    return await input_model_service.list_by_workspace(db, workspace_id)


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post(
    "/workspaces/{workspace_id}/input-models",
    response_model=InputModelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_input_model(
    workspace_id: UUID,
    data: InputModelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("workspace", "MANAGER")),
) -> InputModelResponse:
    """Cria um novo modelo de entrada no workspace."""
    return await input_model_service.create(db, workspace_id, data, current_user.id)


# ─── Get ──────────────────────────────────────────────────────────────────────

@router.get(
    "/input-models/{input_model_id}",
    response_model=InputModelResponse,
)
async def get_input_model(
    input_model_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> InputModelResponse:
    """Retorna um modelo de entrada pelo ID."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")
    return model


# ─── Update ───────────────────────────────────────────────────────────────────

@router.put(
    "/input-models/{input_model_id}",
    response_model=InputModelResponse,
)
async def update_input_model(
    input_model_id: UUID,
    data: InputModelUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> InputModelResponse:
    """Atualiza um modelo de entrada existente."""
    model = await input_model_service.update(db, input_model_id, data)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")
    return model


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete(
    "/input-models/{input_model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_input_model(
    input_model_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> None:
    """Remove um modelo de entrada."""
    deleted = await input_model_service.delete(db, input_model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")


# ─── Download template ────────────────────────────────────────────────────────

@router.get("/input-models/{input_model_id}/template")
async def download_template(
    input_model_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> Response:
    """Baixa o template vazio (Excel ou CSV) do modelo de entrada."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")

    try:
        content, filename, content_type = input_model_service.generate_template(model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Validate file ───────────────────────────────────────────────────────────

@router.post(
    "/input-models/{input_model_id}/validate",
    response_model=ValidationResult,
)
async def validate_file(
    input_model_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> ValidationResult:
    """Valida um arquivo uploadado contra o schema do modelo."""
    model = await input_model_service.get(db, input_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo de entrada nao encontrado.")

    file_bytes = await file.read()
    return input_model_service.validate_file(model, file_bytes, file.filename or "")
