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
from app.schemas.ai_chat import AiChatRequest
from app.services.ai_chat_service import ai_chat_service
from app.services.connection_service import connection_service

router = APIRouter(tags=["ai-chat"])


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
    _=Depends(_require_chat_permission("CLIENT", "CONSULTANT")),
) -> StreamingResponse:
    # Verificar se LLM esta configurado
    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistente SQL nao configurado. Configure LLM_API_KEY nas variaveis de ambiente.",
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
