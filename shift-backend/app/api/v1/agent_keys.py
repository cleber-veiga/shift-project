"""
Endpoints de gerenciamento de chaves de API do Platform Agent.

POST   /agent-keys               → cria (retorna plaintext UMA vez)
GET    /agent-keys               → lista chaves do workspace
POST   /agent-keys/{id}/revoke   → revoga chave (marca revoked_at)
DELETE /agent-keys/{id}          → hard delete

Criacao/revogacao/delete exigem workspace MANAGER. Listagem exige
workspace CONSULTANT.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import authorization_service
from app.models import User
from app.schemas.agent_api_key import (
    AgentApiKeyCreatedResponse,
    AgentApiKeyCreateRequest,
    AgentApiKeyListResponse,
    AgentApiKeyResponse,
)
from app.services.agent.api_key_service import (
    AgentApiKeyPermissionError,
    AgentApiKeyValidationError,
    agent_api_key_service,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/agent-keys", tags=["agent-keys"])


def _require_agent_enabled() -> None:
    if not settings.AGENT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _require_workspace_role(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: UUID,
    required_role: str,
) -> None:
    """Retorna 404 em workspace sem acesso (anti-enumeration) ou 403 sem role."""
    ok = await authorization_service.has_permission(
        db=db,
        user_id=user.id,
        scope="workspace",
        required_role=required_role,
        scope_id=workspace_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para esta operacao.",
        )


@router.post(
    "",
    response_model=AgentApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria uma nova chave de API (retorna plaintext uma unica vez)",
)
async def create_api_key(
    payload: AgentApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentApiKeyCreatedResponse:
    _require_agent_enabled()
    await _require_workspace_role(
        db,
        user=current_user,
        workspace_id=payload.workspace_id,
        required_role="MANAGER",
    )

    try:
        entity, plaintext = await agent_api_key_service.create(
            db,
            creator=current_user,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            name=payload.name,
            max_workspace_role=payload.max_workspace_role,
            max_project_role=payload.max_project_role,
            allowed_tools=payload.allowed_tools,
            require_human_approval=payload.require_human_approval,
            expires_at=payload.expires_at,
        )
    except AgentApiKeyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except AgentApiKeyPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    await db.commit()
    return AgentApiKeyCreatedResponse(
        api_key=plaintext,
        key=AgentApiKeyResponse.model_validate(entity),
    )


@router.get(
    "",
    response_model=AgentApiKeyListResponse,
    summary="Lista chaves de API do workspace (sem plaintext)",
)
async def list_api_keys(
    workspace_id: Annotated[UUID, Query(description="UUID do workspace")],
    include_revoked: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentApiKeyListResponse:
    _require_agent_enabled()
    await _require_workspace_role(
        db,
        user=current_user,
        workspace_id=workspace_id,
        required_role="CONSULTANT",
    )

    rows, total = await agent_api_key_service.list(
        db,
        workspace_id=workspace_id,
        include_revoked=include_revoked,
        limit=limit,
        offset=offset,
    )
    return AgentApiKeyListResponse(
        items=[AgentApiKeyResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.post(
    "/{key_id}/revoke",
    response_model=AgentApiKeyResponse,
    summary="Revoga uma chave de API (marca revoked_at)",
)
async def revoke_api_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentApiKeyResponse:
    _require_agent_enabled()
    key = await agent_api_key_service.get(db, key_id=key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await _require_workspace_role(
        db,
        user=current_user,
        workspace_id=key.workspace_id,
        required_role="MANAGER",
    )
    revoked = await agent_api_key_service.revoke(db, key=key)
    await db.commit()
    logger.info(
        "agent_api_key.revoked",
        api_key_id=str(revoked.id),
        actor_id=str(current_user.id),
    )
    return AgentApiKeyResponse.model_validate(revoked)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Hard delete de uma chave de API",
)
async def delete_api_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _require_agent_enabled()
    key = await agent_api_key_service.get(db, key_id=key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await _require_workspace_role(
        db,
        user=current_user,
        workspace_id=key.workspace_id,
        required_role="MANAGER",
    )
    await agent_api_key_service.delete(db, key=key)
    await db.commit()
    logger.info(
        "agent_api_key.deleted",
        api_key_id=str(key_id),
        actor_id=str(current_user.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
