"""
Schemas Pydantic para a matriz de controle de acesso do workspace.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AccessMatrixProjectEntry(BaseModel):
    project_id: UUID
    project_name: str


class AccessMatrixUserProjectRole(BaseModel):
    project_id: UUID
    explicit_role: str | None
    effective_role: str | None
    source: Literal["explicit", "inherited_ws", "inherited_org", "none"]


class AccessMatrixUserEntry(BaseModel):
    user_id: UUID
    email: str
    full_name: str | None
    is_active: bool
    org_role: str | None
    ws_explicit_role: str | None
    ws_effective_role: str | None
    ws_role_source: Literal["explicit", "inherited_org", "none"]
    project_roles: list[AccessMatrixUserProjectRole]


class AccessMatrixResponse(BaseModel):
    workspace_id: UUID
    workspace_name: str
    organization_id: UUID
    projects: list[AccessMatrixProjectEntry]
    users: list[AccessMatrixUserEntry]
