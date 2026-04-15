"""
Schemas Pydantic para workspaces e concorrentes.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import WorkspacePlayerDatabaseType


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class WorkspaceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime
    my_role: str | None = None


class WorkspacePlayerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    database_type: WorkspacePlayerDatabaseType


class WorkspacePlayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    database_type: WorkspacePlayerDatabaseType | None = None


class WorkspacePlayerResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    database_type: WorkspacePlayerDatabaseType
