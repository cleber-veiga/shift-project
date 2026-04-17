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
    deep_reasoning: bool = Field(
        default=False,
        description=(
            "Quando True, usa o modelo de reasoning configurado (LLM_REASONING_MODEL). "
            "Mais lento e mais caro, porem com melhor qualidade em queries analiticas."
        ),
    )


class AiMemoryCreate(BaseModel):
    """Payload para registrar uma query util aplicada pelo usuario."""

    query: str = Field(..., min_length=1, max_length=16_000)
    description: str | None = Field(default=None, max_length=500)


class AiMemoryResponse(BaseModel):
    """Memoria retornada ao cliente."""

    id: str
    query: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
