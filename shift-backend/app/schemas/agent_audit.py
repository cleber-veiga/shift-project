"""
Schemas Pydantic para endpoints de auditoria do Platform Agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditEntryResponse(BaseModel):
    """Linha resumida da lista de auditoria."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thread_id: UUID
    approval_id: UUID | None
    user_id: UUID
    tool_name: str
    status: Literal["success", "error"]
    duration_ms: int | None
    error_message: str | None
    created_at: datetime


class AuditEntryDetail(BaseModel):
    """Detalhe completo de uma entrada de auditoria (inclui raw + metadata)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thread_id: UUID
    approval_id: UUID | None
    user_id: UUID
    tool_name: str
    tool_arguments: dict[str, Any]
    tool_result_preview: str | None
    status: Literal["success", "error"]
    error_message: str | None
    duration_ms: int | None
    log_metadata: dict[str, Any] | None
    created_at: datetime


class AuditListResponse(BaseModel):
    """Lista paginada com contagem total."""

    items: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int


class ToolUsageItem(BaseModel):
    tool_name: str
    count: int


class UserUsageItem(BaseModel):
    user_id: str
    count: int


class AuditStatsResponse(BaseModel):
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float = Field(ge=0.0, le=1.0)
    top_tools: list[ToolUsageItem]
    top_users: list[UserUsageItem]
