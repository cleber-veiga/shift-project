"""
Bridge entre a chave de API e o runtime do Platform Agent (grafo + tools).

Toda chamada MCP atravessa este servico:
  1. Garante uma thread sintetica dedicada a esta chave (audit precisa
     de FK para agent_threads).
  2. Constroi um UserContext com as roles capadas pela chave
     (max_workspace_role / max_project_role).
  3. Se a tool exige aprovacao e a chave exige aprovacao humana,
     cria um AgentApproval (status=pending) e retorna sem executar.
  4. Caso contrario (ou com approval_id valido), despacha via
     execute_tool() e grava audit com metadata.source="mcp" +
     api_key_id.

Nao ha novo modelo/migration nesta fase: a thread sintetica reusa
agent_threads; o vinculo MCP vive em agent_audit_log.log_metadata.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_api_key import AgentApiKey
from app.models.agent_approval import AgentApproval
from app.services.agent.context import UserContext
from app.services.agent.persistence import (
    create_approval,
    ensure_thread,
    write_audit_log,
)
from app.services.agent.tools.registry import TOOL_REGISTRY, execute_tool

logger = get_logger(__name__)

# Namespace estavel para derivar thread_id a partir do api_key.id.
# Valor arbitrario fixo — nao precisa ser secreto.
_MCP_THREAD_NAMESPACE = uuid.UUID("6b7d2a9e-5b1f-4c8e-9a33-2cf0a1b3d4e5")


class MCPBridgeError(Exception):
    """Erro de negocio da bridge MCP."""


class MCPToolNotAllowedError(MCPBridgeError):
    """Tool fora do allowed_tools da chave (403)."""


class MCPApprovalRequiredError(MCPBridgeError):
    """Tool destrutiva aguardando aprovacao humana (202)."""

    def __init__(self, approval_id: UUID, expires_at: datetime) -> None:
        super().__init__("Tool requer aprovacao humana.")
        self.approval_id = approval_id
        self.expires_at = expires_at


class MCPApprovalInvalidError(MCPBridgeError):
    """approval_id invalido / de outra thread / nao aprovado / expirado (400/403)."""


@dataclass(frozen=True)
class MCPExecutionResult:
    status: str  # "success" | "error"
    result: str
    audit_log_id: UUID
    duration_ms: int


def _is_tool_allowed(api_key: AgentApiKey, tool_name: str) -> bool:
    allowed = api_key.allowed_tools or []
    return "*" in allowed or tool_name in allowed


def _mcp_thread_id_for_key(api_key_id: UUID) -> UUID:
    """Gera UUID deterministico para a thread sintetica desta chave."""
    return uuid.uuid5(_MCP_THREAD_NAMESPACE, f"mcp:{api_key_id}")


def build_user_context(api_key: AgentApiKey) -> UserContext:
    """UserContext com roles capadas pela chave.

    O escopo (workspace_id/project_id) e o inerente da chave; as roles sao
    os tetos definidos em create() e ja validados contra o criador.
    organization_role fica None — tools atuais nao dependem dele.
    """
    return UserContext(
        user_id=api_key.created_by,
        workspace_id=api_key.workspace_id,
        project_id=api_key.project_id,
        workspace_role=api_key.max_workspace_role,
        project_role=api_key.max_project_role,
        organization_id=api_key.workspace_id,  # fallback seguro
        organization_role=None,
    )


class MCPBridgeService:
    async def ensure_mcp_thread(
        self,
        db: AsyncSession,
        *,
        api_key: AgentApiKey,
    ) -> UUID:
        """Cria (uma unica vez) a thread sintetica dedicada a esta chave."""
        thread_id = _mcp_thread_id_for_key(api_key.id)
        await ensure_thread(
            db,
            thread_id=thread_id,
            user_id=api_key.created_by,
            workspace_id=api_key.workspace_id,
            project_id=api_key.project_id,
            initial_context={
                "source": "mcp",
                "api_key_id": str(api_key.id),
                "api_key_prefix": api_key.prefix,
            },
            title=f"MCP: {api_key.name}",
        )
        return thread_id

    async def execute(
        self,
        db: AsyncSession,
        *,
        api_key: AgentApiKey,
        tool_name: str,
        arguments: dict[str, Any],
        approval_id: UUID | None,
    ) -> MCPExecutionResult:
        """Executa uma tool via chave de API.

        - Se tool nao esta em allowed_tools → MCPToolNotAllowedError.
        - Se requires_approval e require_human_approval=True:
          * sem approval_id → cria approval + MCPApprovalRequiredError.
          * com approval_id valido/approved → executa + linka na audit.
        - Senao executa direto.
        """
        if tool_name not in TOOL_REGISTRY:
            raise MCPBridgeError(f"Tool desconhecida: {tool_name}")
        if not _is_tool_allowed(api_key, tool_name):
            raise MCPToolNotAllowedError(
                f"Tool '{tool_name}' fora do allowed_tools desta chave."
            )

        thread_id = await self.ensure_mcp_thread(db, api_key=api_key)
        entry = TOOL_REGISTRY[tool_name]
        tool_requires_approval = bool(entry["requires_approval"])
        need_approval = tool_requires_approval and api_key.require_human_approval

        resolved_approval_id: UUID | None = None
        if need_approval:
            if approval_id is None:
                proposed_plan = {
                    "source": "mcp",
                    "api_key_id": str(api_key.id),
                    "tool": tool_name,
                    "arguments": arguments,
                }
                new_id = await create_approval(
                    db,
                    thread_id=thread_id,
                    proposed_plan=proposed_plan,
                )
                approval = await db.get(AgentApproval, new_id)
                assert approval is not None  # acabamos de criar
                raise MCPApprovalRequiredError(
                    approval_id=approval.id,
                    expires_at=approval.expires_at,
                )
            approval = await self._load_approved_approval(
                db,
                approval_id=approval_id,
                thread_id=thread_id,
                tool_name=tool_name,
                arguments=arguments,
            )
            resolved_approval_id = approval.id

        ctx = build_user_context(api_key)
        started = time.perf_counter()
        try:
            result = await execute_tool(
                tool_name, arguments, db=db, user_context=ctx, thread_id=thread_id
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            status = "success"
            error_message = None
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            status = "error"
            result = f"Erro na execucao: {exc}"
            error_message = str(exc)
            logger.exception(
                "agent_mcp.execute_failed",
                tool=tool_name,
                api_key_id=str(api_key.id),
            )

        audit_id = await write_audit_log(
            db,
            thread_id=thread_id,
            user_id=api_key.created_by,
            tool_name=tool_name,
            tool_arguments=arguments,
            status=status,
            approval_id=resolved_approval_id,
            tool_result_preview=result[:2000] if result else None,
            error_message=error_message,
            duration_ms=duration_ms,
            log_metadata={
                "source": "mcp",
                "api_key_id": str(api_key.id),
                "api_key_prefix": api_key.prefix,
            },
        )
        logger.info(
            "agent_mcp.execute",
            tool=tool_name,
            api_key_id=str(api_key.id),
            status=status,
            duration_ms=duration_ms,
            audit_log_id=str(audit_id),
        )
        return MCPExecutionResult(
            status=status,
            result=result,
            audit_log_id=audit_id,
            duration_ms=duration_ms,
        )

    async def get_approval(
        self,
        db: AsyncSession,
        *,
        api_key: AgentApiKey,
        approval_id: UUID,
    ) -> AgentApproval:
        """Retorna approval se pertencer a thread sintetica desta chave."""
        thread_id = _mcp_thread_id_for_key(api_key.id)
        stmt = select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.thread_id == thread_id,
        )
        approval = (await db.execute(stmt)).scalar_one_or_none()
        if approval is None:
            raise MCPBridgeError("Approval nao encontrada para esta chave.")
        return approval

    # --- helpers privados -------------------------------------------------

    async def _load_approved_approval(
        self,
        db: AsyncSession,
        *,
        approval_id: UUID,
        thread_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AgentApproval:
        stmt = select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.thread_id == thread_id,
        )
        approval = (await db.execute(stmt)).scalar_one_or_none()
        if approval is None:
            raise MCPApprovalInvalidError(
                "Approval nao encontrada para esta chave."
            )
        if approval.status != "approved":
            raise MCPApprovalInvalidError(
                f"Approval em status '{approval.status}', nao executavel."
            )
        plan = approval.proposed_plan or {}
        if plan.get("tool") != tool_name or plan.get("arguments") != arguments:
            raise MCPApprovalInvalidError(
                "Tool/arguments nao coincidem com o plano aprovado."
            )
        return approval


mcp_bridge_service = MCPBridgeService()
