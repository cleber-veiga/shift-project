"""
Schemas Pydantic para organizacoes.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    billing_email: EmailStr | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    billing_email: EmailStr | None = None


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    billing_email: str | None = None
    created_at: datetime
    my_role: str | None = None
