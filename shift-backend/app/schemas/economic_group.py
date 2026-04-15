"""
Schemas Pydantic para grupos economicos e estabelecimentos.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EconomicGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True


class EconomicGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class EconomicGroupResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EstablishmentCreate(BaseModel):
    corporate_name: str = Field(..., min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    cnpj: str = Field(..., min_length=14, max_length=14)
    erp_code: int | None = None
    cnae: str = Field(..., min_length=1, max_length=20)
    state_registration: str | None = Field(default=None, max_length=40)
    cep: str | None = Field(default=None, min_length=8, max_length=8)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    notes: str | None = None
    is_active: bool = True


class EstablishmentUpdate(BaseModel):
    corporate_name: str | None = Field(default=None, min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    cnpj: str | None = Field(default=None, min_length=14, max_length=14)
    erp_code: int | None = None
    cnae: str | None = Field(default=None, min_length=1, max_length=20)
    state_registration: str | None = Field(default=None, max_length=40)
    cep: str | None = Field(default=None, min_length=8, max_length=8)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    notes: str | None = None
    is_active: bool | None = None


class EstablishmentResponse(BaseModel):
    id: UUID
    economic_group_id: UUID
    corporate_name: str
    trade_name: str | None = None
    cnpj: str
    erp_code: int | None = None
    cnae: str
    state_registration: str | None = None
    cep: str | None = None
    city: str | None = None
    state: str | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
