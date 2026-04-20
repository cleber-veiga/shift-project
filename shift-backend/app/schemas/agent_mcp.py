"""
Schemas Pydantic da bridge MCP (/agent-mcp/*).

A bridge e consumida pelo shift-mcp-server externo. Cada request traz
a chave de API no header Authorization; as respostas carregam apenas
o minimo necessario para o servidor MCP operar (sem expor hash nem
informacoes sensiveis de outros usuarios).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /agent-mcp/validate
# ---------------------------------------------------------------------------


class MCPValidateResponse(BaseModel):
    """Payload retornado ao MCP server quando a chave e valida.

    Inclui escopo efetivo (workspace/projeto) e a lista de tools permitidas
    — o MCP server usa essa informacao para montar os tools dinamicos.
    """

    api_key_id: UUID
    name: str
    prefix: str
    workspace_id: UUID
    project_id: UUID | None
    max_workspace_role: Literal["VIEWER", "CONSULTANT", "MANAGER"]
    max_project_role: Literal["CLIENT", "EDITOR"] | None
    allowed_tools: list[str]
    require_human_approval: bool
    expires_at: datetime | None


# ---------------------------------------------------------------------------
# /agent-mcp/tools
# ---------------------------------------------------------------------------


class MCPToolSchema(BaseModel):
    """Schema OpenAI function calling de uma tool disponivel a esta chave."""

    name: str
    description: str
    parameters: dict[str, Any]
    requires_approval: bool


class MCPToolsResponse(BaseModel):
    tools: list[MCPToolSchema]


# ---------------------------------------------------------------------------
# /agent-mcp/execute
# ---------------------------------------------------------------------------


class MCPExecuteRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: UUID | None = Field(
        default=None,
        description=(
            "Obrigatorio em tools destrutivas quando a chave tem "
            "require_human_approval=True. Obtido via resposta 202 previa."
        ),
    )


class MCPExecuteResponse(BaseModel):
    status: Literal["success", "error", "pending_approval"]
    result: str | None = None
    approval_id: UUID | None = None
    approval_expires_at: datetime | None = None
    audit_log_id: UUID | None = None
    duration_ms: int | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# /agent-mcp/approvals/{id}
# ---------------------------------------------------------------------------


class MCPApprovalStatusResponse(BaseModel):
    id: UUID
    status: Literal["pending", "approved", "rejected", "expired"]
    proposed_plan: dict[str, Any]
    expires_at: datetime
    decided_at: datetime | None = None
    rejection_reason: str | None = None
