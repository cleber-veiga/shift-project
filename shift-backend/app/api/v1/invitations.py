"""
Rotas REST para convites (invitations).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import authorization_service, require_permission
from app.models import InvitationScope, InvitationStatus, User
from app.schemas import (
    AcceptInvitationResponse,
    CreateInvitationRequest,
    InvitationDetailResponse,
    InvitationResponse,
)
from app.services.invitation_service import invitation_service

router = APIRouter(tags=["invitations"])


# ── Criacao de convites por escopo ────────────────────────────────

@router.post(
    "/organizations/{org_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_org_invitation(
    org_id: UUID,
    payload: CreateInvitationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("organization", "MANAGER")),
) -> InvitationResponse:
    return await invitation_service.create_invitation(
        db, payload.email, InvitationScope.ORGANIZATION, org_id, payload.role, current_user
    )


@router.post(
    "/workspaces/{ws_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ws_invitation(
    ws_id: UUID,
    payload: CreateInvitationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("workspace", "MANAGER")),
) -> InvitationResponse:
    return await invitation_service.create_invitation(
        db, payload.email, InvitationScope.WORKSPACE, ws_id, payload.role, current_user
    )


@router.post(
    "/projects/{proj_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_proj_invitation(
    proj_id: UUID,
    payload: CreateInvitationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project", "EDITOR")),
) -> InvitationResponse:
    return await invitation_service.create_invitation(
        db, payload.email, InvitationScope.PROJECT, proj_id, payload.role, current_user
    )


# ── Listagem de convites por escopo ──────────────────────────────

@router.get(
    "/organizations/{org_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_org_invitations(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MEMBER")),
) -> list[InvitationResponse]:
    return await invitation_service.list_invitations(db, InvitationScope.ORGANIZATION, org_id)


@router.get(
    "/workspaces/{ws_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_ws_invitations(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[InvitationResponse]:
    return await invitation_service.list_invitations(db, InvitationScope.WORKSPACE, ws_id)


@router.get(
    "/projects/{proj_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_proj_invitations(
    proj_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "CLIENT")),
) -> list[InvitationResponse]:
    return await invitation_service.list_invitations(db, InvitationScope.PROJECT, proj_id)


# ── Gestao de convites individuais ───────────────────────────────

@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_invitation(
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await _check_invitation_permission(db, invitation_id, current_user)
    await invitation_service.cancel_invitation(db, invitation_id)


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
async def resend_invitation(
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvitationResponse:
    await _check_invitation_permission(db, invitation_id, current_user)
    return await invitation_service.resend_invitation(db, invitation_id, current_user)


# ── Endpoints publicos para aceite ───────────────────────────────

@router.get(
    "/invitations/accept/{token}",
    response_model=InvitationDetailResponse,
)
async def get_invitation_detail(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InvitationDetailResponse:
    detail = await invitation_service.get_invitation_by_token(db, token)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Convite nao encontrado.",
        )
    return detail


@router.post(
    "/invitations/accept/{token}",
    response_model=AcceptInvitationResponse,
)
async def accept_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AcceptInvitationResponse:
    return await invitation_service.accept_invitation(db, token, current_user)


# ── Helper de permissao ──────────────────────────────────────────

async def _check_invitation_permission(
    db: AsyncSession, invitation_id: UUID, user: User
) -> None:
    """Verifica se o usuario tem permissao para gerenciar o convite."""
    from app.models import Invitation

    inv = await db.get(Invitation, invitation_id)
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Convite nao encontrado.",
        )

    # Determinar escopo e verificar permissao
    if inv.scope == InvitationScope.ORGANIZATION:
        has = await authorization_service.has_permission(
            db, user.id, "organization", "MANAGER", inv.organization_id
        )
    elif inv.scope == InvitationScope.WORKSPACE:
        has = await authorization_service.has_permission(
            db, user.id, "workspace", "MANAGER", inv.workspace_id
        )
    else:
        has = await authorization_service.has_permission(
            db, user.id, "project", "EDITOR", inv.project_id
        )

    if not has:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para gerenciar este convite.",
        )
