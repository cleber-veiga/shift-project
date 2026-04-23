"""
Wrapper de chamadas ao LLM para os nos do Platform Agent.

Usa LiteLLM para manter consistencia com o ai_chat_service. Expoe duas
APIs: llm_complete (JSON-mode para classificacao/planejamento) e
llm_stream (usado no report_node, que pode gerar texto longo).

Fase 6: expoe LLMResponse com contagem de tokens para auditoria/budget.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import litellm

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """Resposta do LLM com metadados de uso (Fase 6)."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def usage_entry(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
        }


def _common_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.AGENT_LLM_MODEL,
        "temperature": 0.2,
        "max_tokens": 4096,
        "timeout": 30.0,
    }
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        kwargs["api_base"] = settings.LLM_BASE_URL
    return kwargs


def _extract_usage(response: Any) -> tuple[int, int, str]:
    """Extrai (prompt_tokens, completion_tokens, model) da resposta LiteLLM."""
    prompt_tokens = 0
    completion_tokens = 0
    model = getattr(response, "model", "") or settings.AGENT_LLM_MODEL
    usage = getattr(response, "usage", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return prompt_tokens, completion_tokens, str(model)


async def llm_complete_with_usage(
    *,
    system: str,
    user: str,
    json_mode: bool = False,
) -> LLMResponse:
    """Chamada sincrona que retorna conteudo + tokens."""
    kwargs = _common_kwargs()
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await litellm.acompletion(**kwargs)
    except (litellm.Timeout, asyncio.TimeoutError) as exc:
        logger.warning("agent.llm.timeout", model=settings.AGENT_LLM_MODEL)
        raise RuntimeError("LLM timeout: modelo nao respondeu em 30 segundos.") from exc
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError) as exc:
        logger.exception("agent.llm.complete.bad_response")
        raise RuntimeError("Resposta inesperada do LLM") from exc

    prompt_tokens, completion_tokens, model = _extract_usage(response)
    return LLMResponse(
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=model,
    )


async def llm_complete(
    *,
    system: str,
    user: str,
    json_mode: bool = False,
) -> str:
    """Compat: retorna apenas o texto. Prefira llm_complete_with_usage."""
    response = await llm_complete_with_usage(
        system=system, user=user, json_mode=json_mode
    )
    return response.content


async def llm_complete_json_with_usage(
    *,
    system: str,
    user: str,
    fallback: dict[str, Any],
) -> tuple[dict[str, Any], LLMResponse]:
    """Chama em json-mode; retorna (dict, LLMResponse) com fallback em caso de parse."""
    response = await llm_complete_with_usage(
        system=system, user=user, json_mode=True
    )
    try:
        parsed = json.loads(response.content)
        if not isinstance(parsed, dict):
            raise ValueError("top-level nao e objeto")
        return parsed, response
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "agent.llm.json_parse_failed",
            raw_preview=response.content[:200],
        )
        return fallback, response


async def llm_complete_json(
    *,
    system: str,
    user: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Compat: retorna apenas o dict parseado."""
    parsed, _ = await llm_complete_json_with_usage(
        system=system, user=user, fallback=fallback
    )
    return parsed


async def llm_stream(
    *,
    messages: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Streaming de texto simples. Usado por report_node."""
    kwargs = _common_kwargs()
    kwargs["messages"] = messages
    kwargs["stream"] = True

    try:
        response = await litellm.acompletion(**kwargs)
    except (litellm.Timeout, asyncio.TimeoutError) as exc:
        logger.warning("agent.llm.stream.timeout", model=settings.AGENT_LLM_MODEL)
        raise RuntimeError("LLM stream timeout: modelo nao respondeu em 30 segundos.") from exc
    async for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content
