"""
Schemas Pydantic para o Assistente SQL (AI Chat).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    """Uma mensagem na conversa (enviada pelo cliente)."""

    role: str = Field(
        ...,
        pattern=r"^(user|assistant)$",
        description="Papel: 'user' ou 'assistant'",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=16_000,
        description="Conteudo da mensagem",
    )


class AiChatRequest(BaseModel):
    """Payload para o endpoint de chat SSE."""

    messages: list[ChatMessageIn] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Historico de mensagens (inclui a nova pergunta do usuario)",
    )
