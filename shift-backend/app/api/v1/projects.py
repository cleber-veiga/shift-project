"""
Rotas REST para projects e seus membros.
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
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    UpdateMemberRoleRequest,
)
from app.services.b2b_service import b2b_service

router = APIRouter(tags=["projects"])


@router.get("/workspaces/{ws_id}/projects", response_model=list[ProjectResponse])
async def list_projects(
    ws_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProjectResponse]:
    projects = await b2b_service.list_projects_for_user(db, ws_id, current_user.id)
    return [ProjectResponse.model_validate(project, from_attributes=True) for project in projects]


@router.post("/workspaces/{ws_id}/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    ws_id: UUID,
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> ProjectResponse:
    project = await b2b_service.create_project(db, ws_id, data)
    return ProjectResponse.model_validate(project, from_attributes=True)


@router.get("/projects/{proj_id}", response_model=ProjectResponse)
async def get_project(
    proj_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = await b2b_service.get_project_for_user(db, proj_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto nao encontrado.")
    return ProjectResponse.model_validate(project, from_attributes=True)


@router.put("/projects/{proj_id}", response_model=ProjectResponse)
async def update_project(
    proj_id: UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "EDITOR")),
) -> ProjectResponse:
    project = await b2b_service.update_project(db, proj_id, data)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto nao encontrado.")
    return ProjectResponse.model_validate(project, from_attributes=True)


@router.delete("/projects/{proj_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    proj_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "EDITOR")),
) -> None:
    deleted = await b2b_service.delete_project(db, proj_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto nao encontrado.")


@router.get("/projects/{proj_id}/members", response_model=list[MemberResponse])
async def list_project_members(
    proj_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "CLIENT")),
) -> list[MemberResponse]:
    return await b2b_service.list_project_members(db, proj_id)


@router.post("/projects/{proj_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_project_member(
    proj_id: UUID,
    payload: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "EDITOR")),
) -> MemberResponse:
    return await b2b_service.add_project_member(db, proj_id, payload)


@router.put("/projects/{proj_id}/members/{user_id}", response_model=MemberResponse)
async def update_project_member_role(
    proj_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "EDITOR")),
) -> MemberResponse:
    member = await b2b_service.update_project_member_role(db, proj_id, user_id, payload.role)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")
    return member


@router.delete("/projects/{proj_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_member(
    proj_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "EDITOR")),
) -> None:
    deleted = await b2b_service.remove_project_member(db, proj_id, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")
