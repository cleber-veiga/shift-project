"""
Rotas REST para workspaces e seus membros.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import require_permission
from app.models import User
from app.schemas import (
    AccessMatrixResponse,
    AddMemberRequest,
    MemberResponse,
    UpdateMemberRoleRequest,
    WorkspaceCreate,
    WorkspacePlayerCreate,
    WorkspacePlayerResponse,
    WorkspacePlayerUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.b2b_service import b2b_service

router = APIRouter(tags=["workspaces"])


# ─── Schemas internos ─────────────────────────────────────────────────────────

class WorkspaceCreateWithOrg(BaseModel):
    """Payload para criar workspace com organization_id no corpo."""

    name: str = Field(..., min_length=1, max_length=255)
    organization_id: UUID
    erp_id: str | None = None  # ignorado por enquanto, mantido para compatibilidade


# ─── Rotas de listagem/criação por organização ────────────────────────────────

@router.get("/organizations/{org_id}/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkspaceResponse]:
    wss_with_roles = await b2b_service.list_workspaces_with_roles_for_user(db, org_id, current_user.id)
    result = []
    for ws, my_role in wss_with_roles:
        response = WorkspaceResponse.model_validate(ws, from_attributes=True)
        response.my_role = my_role
        result.append(response)
    return result


@router.post(
    "/organizations/{org_id}/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    org_id: UUID,
    data: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permission("organization", "MANAGER")),
) -> WorkspaceResponse:
    workspace = await b2b_service.create_workspace(db, org_id, data, creator_id=current_user.id)
    return WorkspaceResponse.model_validate(workspace, from_attributes=True)


# ─── Alias: /workspaces/organization/{org_id} (compatibilidade frontend) ──────
# IMPORTANTE: esta rota deve ficar ANTES de /workspaces/{ws_id} para evitar
# que "organization" seja interpretado como um UUID de workspace.

@router.get(
    "/workspaces/organization/{org_id}",
    response_model=list[WorkspaceResponse],
)
async def list_workspaces_by_org(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkspaceResponse]:
    """Alias de GET /organizations/{org_id}/workspaces para compatibilidade com o frontend."""
    wss_with_roles = await b2b_service.list_workspaces_with_roles_for_user(db, org_id, current_user.id)
    result = []
    for ws, my_role in wss_with_roles:
        response = WorkspaceResponse.model_validate(ws, from_attributes=True)
        response.my_role = my_role
        result.append(response)
    return result


# ─── Criação direta de workspace com organization_id no body ──────────────────

@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_direct(
    data: WorkspaceCreateWithOrg,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceResponse:
    """
    Cria workspace com organization_id no corpo da requisição.
    Compatível com o frontend que envia POST /workspaces com {name, organization_id}.
    """
    # Verifica permissão manualmente (require_permission não consegue resolver org_id do body)
    from app.core.security import authorization_service

    has_perm = await authorization_service.has_permission(
        db=db,
        user_id=current_user.id,
        scope="organization",
        required_role="MANAGER",
        scope_id=data.organization_id,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sem permissao para criar workspace nesta organizacao.",
        )

    workspace = await b2b_service.create_workspace(
        db, data.organization_id, WorkspaceCreate(name=data.name), creator_id=current_user.id
    )
    return WorkspaceResponse.model_validate(workspace, from_attributes=True)


# ─── Rotas por workspace_id ───────────────────────────────────────────────────

@router.get("/workspaces/{ws_id}", response_model=WorkspaceResponse)
async def get_workspace(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceResponse:
    workspace = await b2b_service.get_workspace_for_user(db, ws_id, current_user.id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace nao encontrado.")
    return WorkspaceResponse.model_validate(workspace, from_attributes=True)


@router.put("/workspaces/{ws_id}", response_model=WorkspaceResponse)
async def update_workspace(
    ws_id: UUID,
    data: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> WorkspaceResponse:
    workspace = await b2b_service.update_workspace(db, ws_id, data)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace nao encontrado.")
    return WorkspaceResponse.model_validate(workspace, from_attributes=True)


@router.delete("/workspaces/{ws_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> None:
    deleted = await b2b_service.delete_workspace(db, ws_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace nao encontrado.")


@router.get("/workspaces/{ws_id}/members", response_model=list[MemberResponse])
async def list_workspace_members(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[MemberResponse]:
    return await b2b_service.list_workspace_members(db, ws_id)


@router.post(
    "/workspaces/{ws_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_member(
    ws_id: UUID,
    payload: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> MemberResponse:
    return await b2b_service.add_workspace_member(db, ws_id, payload)


@router.put("/workspaces/{ws_id}/members/{user_id}", response_model=MemberResponse)
async def update_workspace_member_role(
    ws_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> MemberResponse:
    member = await b2b_service.update_workspace_member_role(db, ws_id, user_id, payload.role)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")
    return member


@router.delete("/workspaces/{ws_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_member(
    ws_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> None:
    deleted = await b2b_service.remove_workspace_member(db, ws_id, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")


@router.get("/workspaces/{ws_id}/access-matrix", response_model=AccessMatrixResponse)
async def get_access_matrix(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> AccessMatrixResponse:
    return await b2b_service.get_workspace_access_matrix(db, ws_id)


@router.get("/workspaces/{ws_id}/players", response_model=list[WorkspacePlayerResponse])
async def list_workspace_players(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[WorkspacePlayerResponse]:
    players = await b2b_service.list_workspace_players(db, ws_id)
    return [WorkspacePlayerResponse.model_validate(player, from_attributes=True) for player in players]


@router.post(
    "/workspaces/{ws_id}/players",
    response_model=WorkspacePlayerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_player(
    ws_id: UUID,
    data: WorkspacePlayerCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> WorkspacePlayerResponse:
    player = await b2b_service.create_workspace_player(db, ws_id, data)
    return WorkspacePlayerResponse.model_validate(player, from_attributes=True)


@router.put("/workspaces/{ws_id}/players/{player_id}", response_model=WorkspacePlayerResponse)
async def update_workspace_player(
    ws_id: UUID,
    player_id: UUID,
    data: WorkspacePlayerUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> WorkspacePlayerResponse:
    player = await b2b_service.update_workspace_player(db, ws_id, player_id, data)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concorrente nao encontrado.")
    return WorkspacePlayerResponse.model_validate(player, from_attributes=True)


@router.delete("/workspaces/{ws_id}/players/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_player(
    ws_id: UUID,
    player_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> None:
    deleted = await b2b_service.delete_workspace_player(db, ws_id, player_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concorrente nao encontrado.")
