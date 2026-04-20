"""
Bridge HTTP consumida pelo shift-mcp-server externo.

A bridge autentica via Authorization: Bearer <api_key_plaintext> e
proxia para o registry de tools do Platform Agent. Todas as execucoes
registram em agent_audit_log com metadata.source="mcp" + api_key_id.

Rotas:
  POST   /agent-mcp/validate          → metadados do token (escopo/tools)
  GET    /agent-mcp/tools             → schemas das tools permitidas
  POST   /agent-mcp/execute           → dispara tool (200/202/4xx)
  GET    /agent-mcp/approvals/{id}    → polling do status de aprovacao

Todos os endpoints retornam 404 quando AGENT_ENABLED=False.
"""

from __future__ import annotations

from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.models.agent_api_key import AgentApiKey
from app.schemas.agent_mcp import (
    MCPApprovalStatusResponse,
    MCPExecuteRequest,
    MCPExecuteResponse,
    MCPToolSchema,
    MCPToolsResponse,
    MCPValidateResponse,
)
from app.services.agent.api_key_service import agent_api_key_service
from app.services.agent.mcp_bridge_service import (
    MCPApprovalInvalidError,
    MCPApprovalRequiredError,
    MCPBridgeError,
    MCPToolNotAllowedError,
    mcp_bridge_service,
)
from app.services.agent.safety.budget_service import agent_budget_service
from app.services.agent.tools.registry import TOOL_REGISTRY

logger = get_logger(__name__)

router = APIRouter(prefix="/agent-mcp", tags=["agent-mcp"])

_bearer_scheme = HTTPBearer(auto_error=False)


def _require_agent_enabled() -> None:
    if not settings.AGENT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _resolve_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AgentApiKey:
    """Valida o Bearer token e retorna a entidade AgentApiKey viva."""
    _require_agent_enabled()
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    api_key = await agent_api_key_service.validate(
        db, plaintext_key=credentials.credentials
    )
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API invalida, revogada ou expirada.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # validate() atualizou last_used_at/usage_count — comita.
    await db.commit()
    return api_key


def _serialize_tools_for_key(api_key: AgentApiKey) -> list[MCPToolSchema]:
    wildcard = "*" in (api_key.allowed_tools or [])
    allowed_names = set(api_key.allowed_tools or [])
    out: list[MCPToolSchema] = []
    for name, entry in TOOL_REGISTRY.items():
        if not wildcard and name not in allowed_names:
            continue
        fn = entry["schema"]["function"]
        out.append(
            MCPToolSchema(
                name=name,
                description=fn["description"],
                parameters=fn.get("parameters", {"type": "object", "properties": {}}),
                requires_approval=bool(entry["requires_approval"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# POST /agent-mcp/validate
# ---------------------------------------------------------------------------


@router.post(
    "/validate",
    response_model=MCPValidateResponse,
    summary="Valida a chave e retorna escopo + tools permitidas",
)
async def validate_api_key(
    api_key: AgentApiKey = Depends(_resolve_api_key),
) -> MCPValidateResponse:
    return MCPValidateResponse(
        api_key_id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        workspace_id=api_key.workspace_id,
        project_id=api_key.project_id,
        max_workspace_role=api_key.max_workspace_role,  # type: ignore[arg-type]
        max_project_role=api_key.max_project_role,  # type: ignore[arg-type]
        allowed_tools=list(api_key.allowed_tools or []),
        require_human_approval=api_key.require_human_approval,
        expires_at=api_key.expires_at,
    )


# ---------------------------------------------------------------------------
# GET /agent-mcp/tools
# ---------------------------------------------------------------------------


@router.get(
    "/tools",
    response_model=MCPToolsResponse,
    summary="Lista schemas das tools que esta chave pode executar",
)
async def list_allowed_tools(
    api_key: AgentApiKey = Depends(_resolve_api_key),
) -> MCPToolsResponse:
    return MCPToolsResponse(tools=_serialize_tools_for_key(api_key))


# ---------------------------------------------------------------------------
# POST /agent-mcp/execute
# ---------------------------------------------------------------------------


@router.post(
    "/execute",
    response_model=MCPExecuteResponse,
    summary="Executa uma tool (ou cria approval pendente)",
)
async def execute_tool_via_mcp(
    payload: Annotated[MCPExecuteRequest, Body()],
    api_key: AgentApiKey = Depends(_resolve_api_key),
    db: AsyncSession = Depends(get_db),
) -> MCPExecuteResponse:
    """Despacha para o registry de tools, mediando approval quando aplicavel.

    Budget destrutivo e aplicado antes da execucao quando a tool exige
    aprovacao (mesmo criterio do fluxo /agent/approve do chat).
    """
    # Budget destrutivo: aplica antes de iniciar a execucao de ferramentas
    # que exigem aprovacao. Nao bloqueia reads (same as chat flow).
    entry = TOOL_REGISTRY.get(payload.tool)
    if entry is not None and entry["requires_approval"]:
        budget = await agent_budget_service.check_destructive_budget(
            db,
            user_id=api_key.created_by,
            workspace_id=api_key.workspace_id,
        )
        if not budget.ok:
            retry = max(1, int(budget.retry_after_seconds or 3600))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=budget.reason or "Limite destrutivo excedido.",
                headers={"Retry-After": str(retry)},
            )

    try:
        result = await mcp_bridge_service.execute(
            db,
            api_key=api_key,
            tool_name=payload.tool,
            arguments=payload.arguments,
            approval_id=payload.approval_id,
        )
    except MCPToolNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except MCPApprovalRequiredError as exc:
        await db.commit()
        return MCPExecuteResponse(
            status="pending_approval",
            approval_id=exc.approval_id,
            approval_expires_at=exc.expires_at,
        )
    except MCPApprovalInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except MCPBridgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await db.commit()
    return MCPExecuteResponse(
        status=result.status,  # "success" | "error"
        result=result.result,
        audit_log_id=result.audit_log_id,
        duration_ms=result.duration_ms,
        error=None if result.status == "success" else result.result,
    )


# ---------------------------------------------------------------------------
# GET /agent-mcp/approvals/{approval_id}
# ---------------------------------------------------------------------------


@router.get(
    "/approvals/{approval_id}",
    response_model=MCPApprovalStatusResponse,
    summary="Consulta status de uma aprovacao pendente (polling)",
)
async def get_approval_status(
    approval_id: UUID,
    api_key: AgentApiKey = Depends(_resolve_api_key),
    db: AsyncSession = Depends(get_db),
) -> MCPApprovalStatusResponse:
    try:
        approval = await mcp_bridge_service.get_approval(
            db, api_key=api_key, approval_id=approval_id
        )
    except MCPBridgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return MCPApprovalStatusResponse(
        id=approval.id,
        status=approval.status,  # type: ignore[arg-type]
        proposed_plan=approval.proposed_plan,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        rejection_reason=approval.rejection_reason,
    )
