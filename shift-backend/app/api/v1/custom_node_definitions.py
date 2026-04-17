"""
Endpoints REST para gerenciamento de definicoes de nos personalizados.

Um "no personalizado" e um blueprint reutilizavel de escritas em multiplas
tabelas relacionadas. Cada definicao aparece na paleta do editor como se
fosse um no nativo.
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import authorization_service, require_permission
from app.models import Project, User
from app.schemas.custom_node_definition import (
    CustomNodeDefinitionCreate,
    CustomNodeDefinitionResponse,
    CustomNodeDefinitionUpdate,
)
from app.services.custom_node_definition_service import custom_node_definition_service

router = APIRouter(tags=["custom-node-definitions"])


async def _check_create_permission(
    db: AsyncSession,
    current_user: User,
    data: CustomNodeDefinitionCreate,
) -> None:
    """Permissao de criacao — MANAGER no workspace ou EDITOR no projeto."""
    if data.project_id is not None:
        allowed = await authorization_service.has_permission(
            db=db,
            user_id=current_user.id,
            scope="project",
            required_role="EDITOR",
            scope_id=data.project_id,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sem permissao para executar esta operacao.",
            )
        return

    if data.workspace_id is not None:
        allowed = await authorization_service.has_permission(
            db=db,
            user_id=current_user.id,
            scope="workspace",
            required_role="MANAGER",
            scope_id=data.workspace_id,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sem permissao para executar esta operacao.",
            )


def _require_definition_permission(
    project_role: str,
    workspace_role: str,
):
    async def dependency(
        definition_id: uuid.UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        definition = await custom_node_definition_service.get(db, definition_id)
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Definicao de no nao encontrada.",
            )

        if definition.project_id is not None:
            await require_permission("project", project_role)(
                request=request,
                db=db,
                current_user=current_user,
            )
            return

        await require_permission("workspace", workspace_role)(
            request=request,
            db=db,
            current_user=current_user,
        )

    return dependency


@router.get(
    "/custom-node-definitions",
    response_model=list[CustomNodeDefinitionResponse],
)
async def list_workspace_definitions(
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[CustomNodeDefinitionResponse]:
    """Lista definicoes do workspace."""
    return await custom_node_definition_service.list(db, workspace_id)


@router.get(
    "/projects/{project_id}/custom-node-definitions",
    response_model=list[CustomNodeDefinitionResponse],
)
async def list_project_definitions(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "CLIENT")),
) -> list[CustomNodeDefinitionResponse]:
    """Lista definicoes do projeto e do workspace pai (herdadas)."""
    workspace_id = await db.scalar(
        select(Project.workspace_id).where(Project.id == project_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projeto nao encontrado.",
        )
    return await custom_node_definition_service.list_for_project(
        db, project_id, workspace_id
    )


@router.post(
    "/custom-node-definitions",
    response_model=CustomNodeDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_definition(
    data: CustomNodeDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CustomNodeDefinitionResponse:
    """Cria uma nova definicao de no personalizado."""
    await _check_create_permission(db, current_user, data)
    return await custom_node_definition_service.create(
        db, data, created_by_id=current_user.id
    )


@router.get(
    "/custom-node-definitions/{definition_id}",
    response_model=CustomNodeDefinitionResponse,
)
async def get_definition(
    definition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_definition_permission("CLIENT", "VIEWER")),
) -> CustomNodeDefinitionResponse:
    """Retorna uma definicao pelo ID."""
    definition = await custom_node_definition_service.get(db, definition_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Definicao de no nao encontrada.",
        )
    return definition


@router.put(
    "/custom-node-definitions/{definition_id}",
    response_model=CustomNodeDefinitionResponse,
)
async def update_definition(
    definition_id: uuid.UUID,
    data: CustomNodeDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_definition_permission("EDITOR", "MANAGER")),
) -> CustomNodeDefinitionResponse:
    """Atualiza parcialmente uma definicao."""
    definition = await custom_node_definition_service.update(db, definition_id, data)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Definicao de no nao encontrada.",
        )
    return definition


@router.post(
    "/custom-node-definitions/{definition_id}/duplicate",
    response_model=CustomNodeDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_definition(
    definition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_definition_permission("EDITOR", "MANAGER")),
) -> CustomNodeDefinitionResponse:
    """
    Duplica a definicao como nova versao (rascunho). Retorna o clone com
    version = max(version) + 1 e is_published=False.
    """
    clone = await custom_node_definition_service.duplicate(
        db, definition_id, created_by_id=current_user.id
    )
    if clone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Definicao de no nao encontrada.",
        )
    return clone


@router.delete(
    "/custom-node-definitions/{definition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_definition(
    definition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_definition_permission("EDITOR", "MANAGER")),
) -> None:
    """Remove uma definicao permanentemente."""
    deleted = await custom_node_definition_service.delete(db, definition_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Definicao de no nao encontrada.",
        )
