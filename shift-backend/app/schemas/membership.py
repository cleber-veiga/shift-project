"""
Schemas Pydantic para memberships.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(..., min_length=1, max_length=32)


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)


class MemberResponse(BaseModel):
    user_id: UUID
    email: str
    is_active: bool
    role: str
    created_at: datetime
