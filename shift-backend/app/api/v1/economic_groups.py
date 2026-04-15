"""
Rotas REST para grupos economicos e estabelecimentos.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import require_permission
from app.models import User
from app.schemas import (
    EconomicGroupCreate,
    EconomicGroupResponse,
    EconomicGroupUpdate,
    EstablishmentCreate,
    EstablishmentResponse,
    EstablishmentUpdate,
)
from app.services.b2b_service import b2b_service

router = APIRouter(tags=["economic-groups"])


@router.get(
    "/organizations/{org_id}/economic-groups",
    response_model=list[EconomicGroupResponse],
)
async def list_economic_groups(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EconomicGroupResponse]:
    groups = await b2b_service.list_economic_groups_for_user(db, org_id, current_user.id)
    return [EconomicGroupResponse.model_validate(group, from_attributes=True) for group in groups]


@router.post(
    "/organizations/{org_id}/economic-groups",
    response_model=EconomicGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_economic_group(
    org_id: UUID,
    data: EconomicGroupCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> EconomicGroupResponse:
    group = await b2b_service.create_economic_group(db, org_id, data)
    return EconomicGroupResponse.model_validate(group, from_attributes=True)


@router.get("/economic-groups/{group_id}", response_model=EconomicGroupResponse)
async def get_economic_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EconomicGroupResponse:
    group = await b2b_service.get_economic_group_for_user(db, group_id, current_user.id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grupo economico nao encontrado.",
        )
    return EconomicGroupResponse.model_validate(group, from_attributes=True)


@router.put("/economic-groups/{group_id}", response_model=EconomicGroupResponse)
async def update_economic_group(
    group_id: UUID,
    data: EconomicGroupUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> EconomicGroupResponse:
    group = await b2b_service.update_economic_group(db, group_id, data)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grupo economico nao encontrado.",
        )
    return EconomicGroupResponse.model_validate(group, from_attributes=True)


@router.delete("/economic-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_economic_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> None:
    deleted = await b2b_service.delete_economic_group(db, group_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grupo economico nao encontrado.",
        )


@router.get(
    "/economic-groups/{group_id}/establishments",
    response_model=list[EstablishmentResponse],
)
async def list_establishments(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EstablishmentResponse]:
    establishments = await b2b_service.list_establishments_for_user(db, group_id, current_user.id)
    return [
        EstablishmentResponse.model_validate(establishment, from_attributes=True)
        for establishment in establishments
    ]


@router.post(
    "/economic-groups/{group_id}/establishments",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_establishment(
    group_id: UUID,
    data: EstablishmentCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> EstablishmentResponse:
    establishment = await b2b_service.create_establishment(db, group_id, data)
    return EstablishmentResponse.model_validate(establishment, from_attributes=True)


@router.get("/establishments/{establishment_id}", response_model=EstablishmentResponse)
async def get_establishment(
    establishment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EstablishmentResponse:
    establishment = await b2b_service.get_establishment_for_user(db, establishment_id, current_user.id)
    if establishment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estabelecimento nao encontrado.",
        )
    return EstablishmentResponse.model_validate(establishment, from_attributes=True)


@router.put("/establishments/{establishment_id}", response_model=EstablishmentResponse)
async def update_establishment(
    establishment_id: UUID,
    data: EstablishmentUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> EstablishmentResponse:
    establishment = await b2b_service.update_establishment(db, establishment_id, data)
    if establishment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estabelecimento nao encontrado.",
        )
    return EstablishmentResponse.model_validate(establishment, from_attributes=True)


@router.delete("/establishments/{establishment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_establishment(
    establishment_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "MANAGER")),
) -> None:
    deleted = await b2b_service.delete_establishment(db, establishment_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estabelecimento nao encontrado.",
        )
