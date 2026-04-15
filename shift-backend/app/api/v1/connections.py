"""
Endpoints REST para gerenciamento de conectores de banco de dados.
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import authorization_service, require_permission
from app.models import Project, User
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    TestConnectionResult,
)
from app.services.connection_service import connection_service

router = APIRouter(tags=["connections"])


async def _check_connection_create_permission(
    db: AsyncSession,
    current_user: User,
    data: ConnectionCreate,
) -> None:
    """Verifica permissao usando os IDs do body — chamada inline para evitar dupla leitura do body."""
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


def _require_connection_owner_permission(
    project_role: str,
    workspace_role: str,
):
    async def dependency(
        connection_id: uuid.UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        conn = await connection_service.get(db, connection_id)
        if conn is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conexao nao encontrada.",
            )

        if conn.project_id is not None:
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


@router.get("/connections", response_model=list[ConnectionResponse])
async def list_connections(
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[ConnectionResponse]:
    """Lista conectores do workspace visiveis ao usuario (publicos ou criados por ele)."""
    return await connection_service.list(db, workspace_id, current_user.id)


@router.get("/projects/{project_id}/connections", response_model=list[ConnectionResponse])
async def list_project_connections(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permission("project", "CLIENT")),
) -> list[ConnectionResponse]:
    """Lista conexoes visiveis ao usuario no projeto e no workspace pai."""
    workspace_id = await db.scalar(
        select(Project.workspace_id).where(Project.id == project_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projeto nao encontrado.",
        )
    return await connection_service.list_for_project(db, project_id, workspace_id, current_user.id)


@router.post("/connections", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    data: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectionResponse:
    """Cria um novo conector no escopo de workspace ou projeto."""
    await _check_connection_create_permission(db, current_user, data)
    return await connection_service.create(db, data, created_by_id=current_user.id)


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_connection_owner_permission("CLIENT", "VIEWER")),
) -> ConnectionResponse:
    """Retorna um conector pelo ID."""
    conn = await connection_service.get(db, connection_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conexao nao encontrada.",
        )
    return conn


@router.put("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_connection_owner_permission("EDITOR", "MANAGER")),
) -> ConnectionResponse:
    """Atualiza parcialmente um conector."""
    conn = await connection_service.update(db, connection_id, data)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conexao nao encontrada.",
        )
    return conn


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_connection_owner_permission("EDITOR", "MANAGER")),
) -> None:
    """Remove um conector permanentemente."""
    deleted = await connection_service.delete(db, connection_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conexao nao encontrada.",
        )


@router.post(
    "/connections/{connection_id}/test",
    response_model=TestConnectionResult,
    summary="Testa a conectividade de um conector",
)
async def test_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_connection_owner_permission("CLIENT", "VIEWER")),
) -> TestConnectionResult:
    """Testa a conexao executando SELECT 1 com timeout de 5 segundos."""
    return await connection_service.test_connection(db, connection_id)
