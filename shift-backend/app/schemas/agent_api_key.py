"""
Schemas Pydantic para endpoints de chaves de API do Platform Agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


WorkspaceRoleLiteral = Literal["VIEWER", "CONSULTANT", "MANAGER"]
ProjectRoleLiteral = Literal["CLIENT", "EDITOR"]


class AgentApiKeyCreateRequest(BaseModel):
    """Payload para criar uma nova chave de API."""

    workspace_id: UUID
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    max_workspace_role: WorkspaceRoleLiteral
    max_project_role: ProjectRoleLiteral | None = None
    allowed_tools: list[str] = Field(
        min_length=1,
        description="Lista de nomes de tools liberadas. Use ['*'] para todas.",
    )
    require_human_approval: bool = True
    expires_at: datetime | None = None

    @field_validator("allowed_tools")
    @classmethod
    def _validate_tools(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip() for t in v if t and t.strip()]
        if not cleaned:
            raise ValueError("allowed_tools nao pode ser vazio")
        return cleaned


class AgentApiKeyResponse(BaseModel):
    """Representacao publica de uma chave (sem plaintext nem hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    prefix: str
    workspace_id: UUID
    project_id: UUID | None
    created_by: UUID
    max_workspace_role: str
    max_project_role: str | None
    allowed_tools: list[str]
    require_human_approval: bool
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    usage_count: int
    created_at: datetime


class AgentApiKeyCreatedResponse(BaseModel):
    """Resposta imediata da criacao — contem o plaintext UMA unica vez."""

    api_key: str = Field(description="Plaintext sk_shift_... — exibir apenas uma vez.")
    warning: str = (
        "Esta eh a unica vez que a chave sera exibida. Guarde em local seguro."
    )
    key: AgentApiKeyResponse


class AgentApiKeyListResponse(BaseModel):
    items: list[AgentApiKeyResponse]
    total: int
