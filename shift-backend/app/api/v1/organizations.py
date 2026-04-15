"""
Rotas REST para organizations e seus membros.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import require_permission
from app.models import User
from app.schemas import (
    AddMemberRequest,
    MemberResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    UpdateMemberRoleRequest,
)
from app.services.b2b_service import b2b_service

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OrganizationResponse]:
    orgs_with_roles = await b2b_service.list_organizations_with_roles_for_user(db, current_user.id)
    result = []
    for org, my_role in orgs_with_roles:
        response = OrganizationResponse.model_validate(org, from_attributes=True)
        response.my_role = my_role
        result.append(response)
    return result


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationResponse:
    organization = await b2b_service.create_organization(db, data, current_user)
    return OrganizationResponse.model_validate(organization, from_attributes=True)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationResponse:
    organization = await b2b_service.get_organization_for_user(db, org_id, current_user.id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization nao encontrada.")
    return OrganizationResponse.model_validate(organization, from_attributes=True)


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: UUID,
    data: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> OrganizationResponse:
    organization = await b2b_service.update_organization(db, org_id, data)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization nao encontrada.")
    return OrganizationResponse.model_validate(organization, from_attributes=True)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "OWNER")),
) -> None:
    deleted = await b2b_service.delete_organization(db, org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization nao encontrada.")


@router.get("/{org_id}/members", response_model=list[MemberResponse])
async def list_organization_members(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MEMBER")),
) -> list[MemberResponse]:
    return await b2b_service.list_organization_members(db, org_id)


@router.post("/{org_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_organization_member(
    org_id: UUID,
    payload: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> MemberResponse:
    return await b2b_service.add_organization_member(db, org_id, payload)


@router.put("/{org_id}/members/{user_id}", response_model=MemberResponse)
async def update_organization_member_role(
    org_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> MemberResponse:
    member = await b2b_service.update_organization_member_role(db, org_id, user_id, payload.role)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")
    return member


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization_member(
    org_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> None:
    deleted = await b2b_service.remove_organization_member(db, org_id, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")
