"""
Schemas Pydantic da API do Platform Agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Mensagens
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    id: UUID
    role: Literal["user", "assistant", "tool", "system"]
    content: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_name: str | None
    created_at: datetime
    # Metadados auxiliares persistidos pelo chat_service (ex: token_usage,
    # payload de interrupt, clarification estruturada). O frontend lê para
    # rehidratar cards ao reabrir a thread.
    msg_metadata: dict[str, Any] | None = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Aprovacoes
# ---------------------------------------------------------------------------


class ApprovalResponse(BaseModel):
    id: UUID
    status: Literal["pending", "approved", "rejected", "expired"]
    proposed_plan: dict[str, Any]
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


class CreateThreadRequest(BaseModel):
    workspace_id: UUID
    project_id: UUID | None = None
    screen_context: dict[str, Any] = Field(default_factory=dict)
    initial_message: str | None = Field(None, min_length=1, max_length=8000)


class ThreadResponse(BaseModel):
    id: UUID
    user_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ThreadDetailResponse(ThreadResponse):
    messages: list[MessageResponse]
    pending_approval: ApprovalResponse | None


# ---------------------------------------------------------------------------
# Envio de mensagens
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    screen_context: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Decisoes de aprovacao
# ---------------------------------------------------------------------------


class ApprovalDecisionRequest(BaseModel):
    approval_id: UUID
    reason: str | None = None
