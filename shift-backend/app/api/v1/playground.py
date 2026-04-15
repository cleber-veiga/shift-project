"""
Endpoints REST do Playground SQL — execução de SELECT e introspecção de schema.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import authorization_service, require_permission
from app.models import User
from app.schemas.playground import (
    PlaygroundQueryRequest,
    PlaygroundQueryResponse,
    SchemaResponse,
)
from app.services.connection_service import connection_service
from app.services.playground_service import playground_service

router = APIRouter(tags=["playground"])


def _require_playground_permission(
    project_role: str,
    workspace_role: str,
):
    """Reutiliza o padrão de permissão por conexão."""

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


@router.get(
    "/connections/{connection_id}/schema",
    response_model=SchemaResponse,
    summary="Retorna o schema (tabelas e colunas) da conexão",
)
async def get_schema(
    connection_id: uuid.UUID,
    force: bool = Query(
        default=False,
        description="Se true, ignora o cache e busca o schema diretamente no banco",
    ),
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_playground_permission("CLIENT", "VIEWER")),
) -> SchemaResponse:
    try:
        return await playground_service.get_schema(db, connection_id, force=force)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/connections/{connection_id}/query",
    response_model=PlaygroundQueryResponse,
    summary="Executa uma consulta SELECT no banco da conexão",
)
async def execute_query(
    connection_id: uuid.UUID,
    body: PlaygroundQueryRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(_require_playground_permission("CLIENT", "VIEWER")),
) -> PlaygroundQueryResponse:
    try:
        return await playground_service.execute_query(
            db,
            connection_id,
            query=body.query,
            max_rows=body.max_rows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
