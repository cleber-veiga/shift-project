"""
Schemas Pydantic para convites (invitations).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: str = Field(..., min_length=1, max_length=32)


class InvitationResponse(BaseModel):
    id: UUID
    email: str
    scope: str
    role: str
    status: str
    invited_by_name: str | None = None
    invited_by_email: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationDetailResponse(BaseModel):
    """Resposta publica para a pagina de aceite — sem dados sensiveis."""
    id: UUID
    email: str
    scope: str
    scope_name: str
    role: str
    invited_by_name: str | None = None
    is_expired: bool
    is_accepted: bool


class AcceptInvitationResponse(BaseModel):
    success: bool
    message: str
    scope: str
    scope_id: UUID
