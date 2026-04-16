"""
Endpoints REST para consultas SQL salvas.

As queries são vinculadas a (player_id + database_type).
O acesso é feito via connection_id — o endpoint extrai player_id e type da conexão.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import authorization_service, require_permission
from app.models import User
from app.schemas.saved_query import (
    SavedQueryCreate,
    SavedQueryResponse,
    SavedQueryUpdate,
)
from app.services.connection_service import connection_service
from app.services.saved_query_service import saved_query_service

router = APIRouter(tags=["saved-queries"])


async def _get_connection_or_404(db: AsyncSession, connection_id: uuid.UUID):
    """Busca a conexão ou retorna 404."""
    conn = await connection_service.get(db, connection_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conexão não encontrada.",
        )
    if conn.player_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta conexão não está vinculada a um concorrente. Vincule um concorrente para salvar consultas.",
        )
    return conn


def _require_connection_permission(project_role: str, workspace_role: str):
    """Permissao por conexao — mesmo padrao do playground.py."""

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
                detail="Conexão não encontrada.",
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


def _require_query_write_permission():
    """Permissao de escrita por query_id — resolve workspace_id da query."""

    async def dependency(
        query_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        query = await saved_query_service.get(db, query_id)
        if query is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Consulta não encontrada.",
            )

        allowed = await authorization_service.has_permission(
            db=db,
            user_id=current_user.id,
            scope="workspace",
            required_role="CONSULTANT",
            scope_id=query.workspace_id,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sem permissao para executar esta operacao.",
            )

    return dependency


@router.get(
    "/connections/{connection_id}/saved-queries",
    response_model=list[SavedQueryResponse],
    summary="Lista consultas salvas para o concorrente e tipo de banco da conexão",
)
async def list_saved_queries(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_connection_permission("CLIENT", "VIEWER")),
) -> list[SavedQueryResponse]:
    conn = await _get_connection_or_404(db, connection_id)
    items = await saved_query_service.list_for_connection(
        db,
        player_id=conn.player_id,
        database_type=conn.type,
    )
    return [SavedQueryResponse.model_validate(item) for item in items]


@router.post(
    "/connections/{connection_id}/saved-queries",
    response_model=SavedQueryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Salva uma nova consulta SQL para o concorrente e tipo de banco",
)
async def create_saved_query(
    connection_id: uuid.UUID,
    body: SavedQueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_connection_permission("EDITOR", "CONSULTANT")),
) -> SavedQueryResponse:
    conn = await _get_connection_or_404(db, connection_id)

    workspace_id = conn.workspace_id or conn.project_id
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conexão sem workspace associado.",
        )

    try:
        obj = await saved_query_service.create(
            db,
            workspace_id=workspace_id,
            player_id=conn.player_id,
            database_type=conn.type,
            name=body.name,
            description=body.description,
            query=body.query,
            created_by_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        if "uq_saved_query_player_type_name" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Já existe uma consulta com o nome "{body.name}" para este concorrente e tipo de banco.',
            )
        raise

    return SavedQueryResponse.model_validate(obj)


@router.put(
    "/saved-queries/{query_id}",
    response_model=SavedQueryResponse,
    summary="Atualiza uma consulta SQL salva",
)
async def update_saved_query(
    query_id: uuid.UUID,
    body: SavedQueryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_query_write_permission()),
) -> SavedQueryResponse:
    try:
        obj = await saved_query_service.update(
            db,
            query_id,
            name=body.name,
            description=body.description,
            query=body.query,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return SavedQueryResponse.model_validate(obj)


@router.delete(
    "/saved-queries/{query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui uma consulta SQL salva",
)
async def delete_saved_query(
    query_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_query_write_permission()),
) -> None:
    try:
        await saved_query_service.delete(db, query_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
