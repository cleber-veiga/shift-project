"""
Endpoint SSE do Assistente SQL — chat com IA.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.security import require_permission
from app.models import User
from app.schemas.ai_chat import AiChatRequest, AiMemoryCreate, AiMemoryResponse
from app.services.ai_chat_service import ai_chat_service
from app.services.ai_memory_service import ai_memory_service
from app.services.connection_service import connection_service

router = APIRouter(tags=["ai-chat"])


@router.get(
    "/ai-chat/capabilities",
    summary="Capacidades do Assistente SQL (configuracao disponivel)",
)
async def chat_capabilities(
    _user: User = Depends(get_current_user),
) -> dict[str, bool | str | None]:
    """Informa ao frontend quais modos do assistente estao disponiveis."""
    return {
        "enabled": bool(settings.LLM_API_KEY),
        "reasoning_enabled": bool(
            settings.LLM_API_KEY and settings.LLM_REASONING_MODEL
        ),
        "reasoning_effort": settings.LLM_REASONING_EFFORT
        if settings.LLM_REASONING_MODEL
        else None,
    }


def _require_chat_permission(
    project_role: str,
    workspace_role: str,
):
    """Permissao por conexao — mesmo padrao do playground.py."""

    async def dependency(
        connection_id: uuid.UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        conn = await connection_service.get(db, connection_id)
        if conn is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conexao nao encontrada.",
            )

        if conn.project_id is not None:
            await require_permission("project", project_role)(
                request=request,
                db=db,
                current_user=current_user,
            )
            return

        await require_permission("workspace", workspace_role)(
            request=request,
            db=db,
            current_user=current_user,
        )

    return dependency


@router.post(
    "/connections/{connection_id}/chat",
    summary="Chat SSE com o Assistente SQL",
)
async def chat_stream(
    connection_id: uuid.UUID,
    body: AiChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_chat_permission("CLIENT", "CONSULTANT")),
) -> StreamingResponse:
    # Verificar se LLM esta configurado
    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistente SQL nao configurado. Configure LLM_API_KEY nas variaveis de ambiente.",
        )

    # Modo raciocinio profundo exige modelo dedicado configurado
    if body.deep_reasoning and not settings.LLM_REASONING_MODEL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Modo raciocinio profundo nao disponivel. "
                "Configure LLM_REASONING_MODEL nas variaveis de ambiente."
            ),
        )

    # Buscar tipo do banco para o system prompt
    conn = await connection_service.get(db, connection_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conexao nao encontrada.",
        )

    # Converter mensagens para dicts
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    async def generate():
        async for event in ai_chat_service.stream_chat(
            db=db,
            connection_id=connection_id,
            messages=messages,
            db_type=conn.type,
            deep_reasoning=body.deep_reasoning,
            user_id=current_user.id,
        ):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/connections/{connection_id}/chat/memories",
    summary="Registra uma query util gerada pelo assistente (aplicada pelo usuario)",
)
async def create_memory(
    connection_id: uuid.UUID,
    body: AiMemoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_chat_permission("CLIENT", "CONSULTANT")),
) -> AiMemoryResponse:
    try:
        mem = await ai_memory_service.record(
            db,
            connection_id=connection_id,
            user_id=current_user.id,
            query=body.query,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return AiMemoryResponse(
        id=str(mem.id),
        query=mem.query,
        description=mem.description,
        created_at=mem.created_at.isoformat() if mem.created_at else None,
        updated_at=mem.updated_at.isoformat() if mem.updated_at else None,
    )


@router.get(
    "/connections/{connection_id}/chat/memories",
    summary="Lista as memorias recentes do usuario para esta conexao",
)
async def list_memories(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_chat_permission("CLIENT", "CONSULTANT")),
) -> list[AiMemoryResponse]:
    rows = await ai_memory_service.list_recent(
        db,
        connection_id=connection_id,
        user_id=current_user.id,
        limit=20,
    )
    return [AiMemoryResponse(**r) for r in rows]


@router.delete(
    "/connections/{connection_id}/chat/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove uma memoria do assistente",
)
async def delete_memory(
    connection_id: uuid.UUID,  # noqa: ARG001 — usado para permissao
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(_require_chat_permission("CLIENT", "CONSULTANT")),
) -> None:
    await ai_memory_service.delete(db, memory_id=memory_id, user_id=current_user.id)
