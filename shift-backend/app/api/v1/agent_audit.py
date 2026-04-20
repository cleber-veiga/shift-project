"""
Endpoints de auditoria do Platform Agent.

Somente-leitura. Requer workspace MANAGER (para ver tudo do workspace)
ou project EDITOR (para o proprio projeto). Workspace alheio retorna
404, nao 403 — evita enumeration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import authorization_service
from app.models import User
from app.schemas.agent_audit import (
    AuditEntryDetail,
    AuditEntryResponse,
    AuditListResponse,
    AuditStatsResponse,
)
from app.services.agent.audit_service import agent_audit_service

logger = get_logger(__name__)

router = APIRouter(prefix="/agent/audit", tags=["agent-audit"])


def _require_agent_enabled() -> None:
    if not settings.AGENT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _check_audit_permission(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: UUID,
    project_id: UUID | None,
) -> None:
    """Permite workspace MANAGER OU project EDITOR (do proprio projeto).

    Retorna 404 (nao 403) quando o usuario nao tem acesso algum ao
    workspace — evita enumeration de workspaces.
    """
    ws_ok = await authorization_service.has_permission(
        db=db,
        user_id=user.id,
        scope="workspace",
        required_role="MANAGER",
        scope_id=workspace_id,
    )
    if ws_ok:
        return

    if project_id is not None:
        proj_ok = await authorization_service.has_permission(
            db=db,
            user_id=user.id,
            scope="project",
            required_role="EDITOR",
            scope_id=project_id,
        )
        if proj_ok:
            return

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get(
    "/",
    response_model=AuditListResponse,
    summary="Lista entradas do log de auditoria do Platform Agent",
)
async def list_audit(
    workspace_id: Annotated[UUID, Query(description="UUID do workspace")],
    project_id: UUID | None = Query(None),
    user_id: UUID | None = Query(None),
    tool_name: str | None = Query(None, max_length=128),
    audit_status: str | None = Query(
        None, alias="status", pattern="^(success|error)$"
    ),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditListResponse:
    _require_agent_enabled()
    await _check_audit_permission(
        db, user=current_user, workspace_id=workspace_id, project_id=project_id
    )

    rows, total = await agent_audit_service.list(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        tool_name=tool_name,
        status=audit_status,  # type: ignore[arg-type]
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return AuditListResponse(
        items=[AuditEntryResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats",
    response_model=AuditStatsResponse,
    summary="Agregacoes de auditoria do workspace",
)
async def get_stats(
    workspace_id: Annotated[UUID, Query(description="UUID do workspace")],
    project_id: UUID | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditStatsResponse:
    _require_agent_enabled()
    await _check_audit_permission(
        db, user=current_user, workspace_id=workspace_id, project_id=project_id
    )
    stats = await agent_audit_service.stats(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        days=days,
    )
    return AuditStatsResponse(
        total_executions=stats.total_executions,
        successful_executions=stats.successful_executions,
        failed_executions=stats.failed_executions,
        success_rate=stats.success_rate,
        top_tools=[
            {"tool_name": t["tool_name"], "count": t["count"]}
            for t in stats.top_tools
        ],
        top_users=[
            {"user_id": u["user_id"], "count": u["count"]}
            for u in stats.top_users
        ],
    )


@router.get(
    "/{entry_id}",
    response_model=AuditEntryDetail,
    summary="Detalhe de uma entrada de auditoria (raw result + metadata)",
)
async def get_entry(
    entry_id: UUID,
    workspace_id: Annotated[UUID, Query(description="UUID do workspace")],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditEntryDetail:
    _require_agent_enabled()
    await _check_audit_permission(
        db, user=current_user, workspace_id=workspace_id, project_id=None
    )
    entry = await agent_audit_service.get_entry(
        db, entry_id=entry_id, workspace_id=workspace_id
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return AuditEntryDetail.model_validate(entry)
