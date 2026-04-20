"""
Endpoints REST + SSE do Platform Agent.

Todos os endpoints retornam 404 quando AGENT_ENABLED=False — comportamento
de "feature nao existe", nao de "proibido". Isso oculta a feature durante
rollout gradual.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import authorization_service, require_permission
from app.models import User
from app.schemas.agent import (
    ApprovalDecisionRequest,
    CreateThreadRequest,
    MessageResponse,
    SendMessageRequest,
    ThreadDetailResponse,
    ThreadResponse,
    ApprovalResponse,
)
from app.db.session import async_session_factory
from app.services.agent.chat_service import agent_chat_service
from app.services.agent.safety.budget_service import agent_budget_service
from app.services.agent.thread_service import thread_service

logger = get_logger(__name__)


async def _enforce_message_budget(
    db: AsyncSession,
    *,
    user_id: UUID,
    workspace_id: UUID,
) -> None:
    """Aplica budget de mensagens; 429 + Retry-After se excedido."""
    result = await agent_budget_service.check_message_budget(
        db, user_id=user_id, workspace_id=workspace_id
    )
    if not result.ok:
        retry = max(1, int(result.retry_after_seconds or 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result.reason or "Limite de mensagens excedido.",
            headers={"Retry-After": str(retry)},
        )


async def _enforce_token_hard_cap(
    db: AsyncSession,
    *,
    user_id: UUID,
    thread_id: UUID | None,
    workspace_id: UUID,
) -> None:
    """Bloqueia apenas se o hard cap (user/dia) foi atingido; soft cap
    (per-thread) e tratado dentro do grafo pelo planner."""
    result = await agent_budget_service.check_token_budget(
        db,
        user_id=user_id,
        thread_id=thread_id,
        workspace_id=workspace_id,
    )
    if not result.ok:
        retry = max(1, int(result.retry_after_seconds or 3600))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result.reason or "Limite de tokens excedido.",
            headers={"Retry-After": str(retry)},
        )


async def _enforce_destructive_budget(
    db: AsyncSession,
    *,
    user_id: UUID,
    workspace_id: UUID,
) -> None:
    """Aplica budget de execucoes destrutivas (usado em /approve)."""
    result = await agent_budget_service.check_destructive_budget(
        db, user_id=user_id, workspace_id=workspace_id
    )
    if not result.ok:
        retry = max(1, int(result.retry_after_seconds or 3600))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result.reason or "Limite de execucoes destrutivas excedido.",
            headers={"Retry-After": str(retry)},
        )

router = APIRouter(prefix="/agent", tags=["agent"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _require_agent_enabled() -> None:
    """Retorna 404 se AGENT_ENABLED=False — oculta existencia da feature."""
    if not settings.AGENT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _agent_flag_dep() -> None:
    _require_agent_enabled()


# ---------------------------------------------------------------------------
# POST /agent/threads
# ---------------------------------------------------------------------------


@router.post(
    "/threads",
    summary="Cria uma thread do Platform Agent",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def create_thread(
    request: Request,
    body: Annotated[CreateThreadRequest, Body()],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
):
    """Cria thread. Com initial_message retorna SSE; sem, retorna JSON 201."""
    has_perm = await authorization_service.has_permission(
        db=db,
        user_id=current_user.id,
        scope="workspace",
        required_role="CONSULTANT",
        scope_id=body.workspace_id,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sem permissao para usar o agente neste workspace.",
        )

    initial_context: dict = {
        "workspace_id": str(body.workspace_id),
        "project_id": str(body.project_id) if body.project_id else None,
        "screen_context": body.screen_context,
    }
    title = (body.initial_message or "")[:80] or None

    thread = await thread_service.create(
        db,
        user_id=current_user.id,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        initial_context=initial_context,
        title=title,
    )

    if body.initial_message:
        await _enforce_message_budget(
            db, user_id=current_user.id, workspace_id=body.workspace_id
        )
        await _enforce_token_hard_cap(
            db,
            user_id=current_user.id,
            thread_id=thread.id,
            workspace_id=body.workspace_id,
        )

        async def _generate() -> AsyncGenerator[str, None]:
            from app.services.agent.events import EVT_THREAD_CREATED, sse_event
            async with async_session_factory() as db_stream:
                stream_thread = await thread_service.get(
                    db_stream,
                    thread_id=thread.id,
                    user_id=current_user.id,
                )
                yield sse_event(EVT_THREAD_CREATED, {"thread_id": str(thread.id)})
                async for chunk in await agent_chat_service.stream_message(
                    db=db_stream,
                    thread=stream_thread,
                    user=current_user,
                    message=body.initial_message,
                    screen_context=body.screen_context or None,
                ):
                    yield chunk

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    return ThreadResponse.model_validate(thread)


# ---------------------------------------------------------------------------
# GET /agent/threads
# ---------------------------------------------------------------------------


@router.get(
    "/threads",
    summary="Lista threads do usuario no workspace",
    response_model=list[ThreadResponse],
)
async def list_threads(
    workspace_id: UUID = Query(..., description="UUID do workspace"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
    _perm: User = Depends(require_permission("workspace", "CONSULTANT")),
) -> list[ThreadResponse]:
    """Lista threads do usuario autenticado no workspace, mais recentes primeiro."""
    threads = await thread_service.list_for_user(
        db,
        user_id=current_user.id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    return [ThreadResponse.model_validate(t) for t in threads]


# ---------------------------------------------------------------------------
# GET /agent/threads/{thread_id}
# ---------------------------------------------------------------------------


@router.get(
    "/threads/{thread_id}",
    summary="Detalhes de uma thread com mensagens e approval pendente",
    response_model=ThreadDetailResponse,
)
async def get_thread(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
) -> ThreadDetailResponse:
    """Retorna thread completa; 404 se nao pertencer ao usuario (evita enumeration)."""
    thread, messages, approval = await thread_service.get_with_messages(
        db, thread_id=thread_id, user_id=current_user.id
    )
    return ThreadDetailResponse(
        id=thread.id,
        user_id=thread.user_id,
        workspace_id=thread.workspace_id,
        project_id=thread.project_id,
        title=thread.title,
        status=thread.status,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
        pending_approval=ApprovalResponse.model_validate(approval) if approval else None,
    )


# ---------------------------------------------------------------------------
# DELETE /agent/threads/{thread_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove uma thread (bloqueado se houver audit_log)",
)
async def delete_thread(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
) -> None:
    """Remove thread; 409 se tiver registros de audit log."""
    await thread_service.delete(db, thread_id=thread_id, user_id=current_user.id)


# ---------------------------------------------------------------------------
# POST /agent/threads/{thread_id}/messages
# ---------------------------------------------------------------------------


@router.post(
    "/threads/{thread_id}/messages",
    summary="Envia mensagem ao agente e recebe stream SSE",
)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    thread_id: UUID,
    body: Annotated[SendMessageRequest, Body()],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
) -> StreamingResponse:
    """Envia mensagem; retorna SSE stream. Exige thread em status ativo."""
    thread = await thread_service.get(db, thread_id=thread_id, user_id=current_user.id)

    if thread.status in {"awaiting_approval", "error"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Thread em status '{thread.status}' nao aceita novas mensagens.",
        )

    if thread.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Thread rejeitada nao aceita novas mensagens.",
        )

    await _enforce_message_budget(
        db, user_id=current_user.id, workspace_id=thread.workspace_id
    )
    await _enforce_token_hard_cap(
        db,
        user_id=current_user.id,
        thread_id=thread.id,
        workspace_id=thread.workspace_id,
    )

    async def _generate() -> AsyncGenerator[str, None]:
        async with async_session_factory() as db_stream:
            stream_thread = await thread_service.get(
                db_stream,
                thread_id=thread.id,
                user_id=current_user.id,
            )
            async for chunk in await agent_chat_service.stream_message(
                db=db_stream,
                thread=stream_thread,
                user=current_user,
                message=body.message,
                screen_context=body.screen_context,
            ):
                yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /agent/threads/{thread_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/threads/{thread_id}/approve",
    summary="Aprova acoes pendentes e retoma o grafo",
)
@limiter.limit("60/minute")
async def approve_actions(
    request: Request,
    thread_id: UUID,
    body: Annotated[ApprovalDecisionRequest, Body()],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
) -> StreamingResponse:
    """Aprova o plan proposto; retoma grafo e retorna SSE."""
    thread = await thread_service.get(db, thread_id=thread_id, user_id=current_user.id)

    if thread.status != "awaiting_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Thread nao esta aguardando aprovacao (status: '{thread.status}').",
        )

    await thread_service.get_pending_approval(
        db, thread_id=thread_id, approval_id=body.approval_id
    )

    await _enforce_destructive_budget(
        db, user_id=current_user.id, workspace_id=thread.workspace_id
    )

    async def _generate() -> AsyncGenerator[str, None]:
        async with async_session_factory() as db_stream:
            stream_thread = await thread_service.get(
                db_stream,
                thread_id=thread.id,
                user_id=current_user.id,
            )
            async for chunk in await agent_chat_service.stream_resume(
                db=db_stream,
                thread=stream_thread,
                user=current_user,
                decision="approved",
                approval_id=body.approval_id,
                reason=body.reason,
            ):
                yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# POST /agent/threads/{thread_id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/threads/{thread_id}/reject",
    summary="Rejeita acoes pendentes e encerra o ciclo de aprovacao",
)
@limiter.limit("60/minute")
async def reject_actions(
    request: Request,
    thread_id: UUID,
    body: Annotated[ApprovalDecisionRequest, Body()],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _flag: None = Depends(_agent_flag_dep),
) -> StreamingResponse:
    """Rejeita o plan proposto; reporta ao usuario e encerra a thread."""
    thread = await thread_service.get(db, thread_id=thread_id, user_id=current_user.id)

    if thread.status != "awaiting_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Thread nao esta aguardando aprovacao (status: '{thread.status}').",
        )

    await thread_service.get_pending_approval(
        db, thread_id=thread_id, approval_id=body.approval_id
    )

    async def _generate() -> AsyncGenerator[str, None]:
        async with async_session_factory() as db_stream:
            stream_thread = await thread_service.get(
                db_stream,
                thread_id=thread.id,
                user_id=current_user.id,
            )
            async for chunk in await agent_chat_service.stream_resume(
                db=db_stream,
                thread=stream_thread,
                user=current_user,
                decision="rejected",
                approval_id=body.approval_id,
                reason=body.reason,
            ):
                yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
