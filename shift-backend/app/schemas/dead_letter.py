"""Schemas da API de dead-letters."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DeadLetterListItem(BaseModel):
    """Item retornado na listagem de dead-letters."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    workflow_id: UUID
    node_id: str
    error_message: str
    payload: dict[str, Any]
    retry_count: int
    created_at: datetime
    resolved_at: datetime | None = None


class DeadLetterListResponse(BaseModel):
    """Resposta paginada da listagem de dead-letters."""

    items: list[DeadLetterListItem]
    total: int
    page: int
    size: int


class DeadLetterRetryResponse(BaseModel):
    """Resultado da tentativa de reprocessamento de um dead-letter."""

    dead_letter_id: UUID
    resolved: bool
    retry_count: int
    status: str
    message: str | None = None
    output: dict[str, Any] | None = None
