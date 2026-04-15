"""
Schemas Pydantic para consultas SQL salvas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SavedQueryCreate(BaseModel):
    """Payload para salvar uma nova consulta."""

    name: str = Field(..., min_length=1, max_length=255, description="Nome descritivo da consulta")
    description: str | None = Field(default=None, max_length=1000, description="Descrição opcional")
    query: str = Field(..., min_length=1, description="Consulta SQL (somente SELECT/WITH)")


class SavedQueryUpdate(BaseModel):
    """Payload para atualizar uma consulta existente."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    query: str | None = Field(default=None, min_length=1)


class SavedQueryResponse(BaseModel):
    """Representação de uma consulta salva."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    player_id: uuid.UUID
    database_type: str
    name: str
    description: str | None
    query: str
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
