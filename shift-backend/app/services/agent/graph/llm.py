"""
Wrapper de chamadas ao LLM para os nos do Platform Agent.

Usa LangChain (init_chat_model) como cliente unico — assim todas as
interacoes com o LLM produzem spans nativos do LangSmith, com input/output
completos, token usage e metadata de modelo. Antes usavamos LiteLLM com
callback "langsmith", que tinha trace parcial (output as vezes null).

API publica estavel (consumida pelos nodes do grafo):
  - LLMResponse                — dataclass com content + tokens
  - llm_complete_with_usage    — completion sincrona com metadata
  - llm_complete               — compat: retorna so o texto
  - llm_complete_json_with_usage / llm_complete_json — completion com parse JSON
  - llm_stream                 — streaming para report_node

Formato do model string em AGENT_LLM_MODEL:
  - "gpt-4o"                              → provider=openai (default)
  - "openai/gpt-4o" ou "openai:gpt-4o"    → provider=openai explicito
  - "anthropic/claude-sonnet-4-20250514"  → provider=anthropic
  - "gemini/gemini-2.0-flash"             → provider=google_genai
  - "ollama/llama3.2"                     → provider=ollama
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

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


# ---------------------------------------------------------------------------
# Bootstrap de observabilidade (LangSmith)
# ---------------------------------------------------------------------------
# LangChain + LangGraph ativam tracing automaticamente quando LANGSMITH_TRACING
# (ou LANGCHAIN_TRACING_V2) esta em os.environ. A funcao abaixo apenas propaga
# as variaveis carregadas pelo Pydantic BaseSettings para o environ do processo,
# porque LangChain nao le .env diretamente.
_OBS_BOOTSTRAPPED = False


def _bootstrap_observability() -> None:
    global _OBS_BOOTSTRAPPED
    if _OBS_BOOTSTRAPPED:
        return
    _OBS_BOOTSTRAPPED = True

    if not settings.LANGSMITH_TRACING:
        logger.debug("agent.observability.disabled")
        return

    if not settings.LANGSMITH_API_KEY:
        logger.warning(
            "agent.observability.missing_api_key",
            hint="LANGSMITH_TRACING=true mas LANGSMITH_API_KEY vazio — desativando.",
        )
        return

    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGSMITH_ENDPOINT

    logger.info(
        "agent.observability.enabled",
        project=settings.LANGSMITH_PROJECT,
        endpoint=settings.LANGSMITH_ENDPOINT,
    )


_bootstrap_observability()


# ---------------------------------------------------------------------------
# Instanciacao do modelo
# ---------------------------------------------------------------------------
# Cache por (model_string, json_mode) — init_chat_model cria um cliente HTTP
# sob o capot. Reutilizar reduz latencia (keep-alive) e evita explodir o numero
# de conexoes em workloads paralelos.
_MODEL_CACHE: dict[tuple[str, bool], Runnable] = {}


def _split_provider(model_string: str) -> tuple[str, str]:
    """Converte 'anthropic/claude-...' ou 'openai:gpt-4o' em (provider, model).

    Default: provider=openai quando nao ha prefixo (ex: 'gpt-4o' sozinho).
    LangChain mapeia: openai, anthropic, google_genai, ollama, etc.
    """
    for sep in (":", "/"):
        if sep in model_string:
            provider, _, model = model_string.partition(sep)
            provider = provider.strip().lower()
            # Aliases: LangChain usa "google_genai" para Gemini; aceitar
            # "gemini" e "google" como sinonimos para facilitar a vida.
            if provider in {"gemini", "google"}:
                provider = "google_genai"
            return provider, model.strip()
    return "openai", model_string.strip()


def _build_model(*, json_mode: bool = False) -> Runnable:
    """Retorna um ChatModel configurado (cached). Em json_mode, faz o bind do
    response_format para instruir o modelo a devolver JSON valido.

    JSON mode:
      - OpenAI: response_format={'type': 'json_object'} e respeitado pelo
        endpoint nativamente.
      - Anthropic: nao tem response_format; o prompt ja orienta "responda
        APENAS com JSON" e o parser faz fallback se algo vier com ruido.
      - Outros providers: bind e ignorado silenciosamente se nao suportarem.
    """
    cache_key = (settings.AGENT_LLM_MODEL, json_mode)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    provider, model_name = _split_provider(settings.AGENT_LLM_MODEL)

    kwargs: dict[str, Any] = {
        "model": model_name,
        "model_provider": provider,
        "temperature": 0.2,
        "timeout": 30.0,
        "max_retries": 1,
    }
    # max_tokens e aceito por openai/anthropic; alguns providers usam nomes
    # diferentes, mas init_chat_model normaliza internamente.
    kwargs["max_tokens"] = 4096
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        # ChatOpenAI aceita base_url; ChatAnthropic aceita base_url tambem.
        kwargs["base_url"] = settings.LLM_BASE_URL

    model: BaseChatModel = init_chat_model(**kwargs)  # type: ignore[assignment]

    runnable: Runnable = model
    if json_mode and provider == "openai":
        runnable = model.bind(response_format={"type": "json_object"})

    _MODEL_CACHE[cache_key] = runnable
    return runnable


def _to_lc_messages(
    *, system: str | None, user: str
) -> list[SystemMessage | HumanMessage]:
    msgs: list[SystemMessage | HumanMessage] = []
    if system:
        msgs.append(SystemMessage(content=system))
    msgs.append(HumanMessage(content=user))
    return msgs


def _extract_usage(message: AIMessage) -> tuple[int, int, str]:
    """Le tokens e nome do modelo da resposta do LangChain.

    AIMessage.usage_metadata e o caminho unificado (input_tokens,
    output_tokens, total_tokens). Alguns providers preenchem tambem
    response_metadata['model_name']. Caimos em fallback para AGENT_LLM_MODEL
    quando nada vem.
    """
    usage = getattr(message, "usage_metadata", None) or {}
    prompt_tokens = int(usage.get("input_tokens", 0) or 0)
    completion_tokens = int(usage.get("output_tokens", 0) or 0)

    model = ""
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        model = str(meta.get("model_name") or meta.get("model") or "")
    if not model:
        model = settings.AGENT_LLM_MODEL
    return prompt_tokens, completion_tokens, model


async def llm_complete_with_usage(
    *,
    system: str,
    user: str,
    json_mode: bool = False,
) -> LLMResponse:
    """Chamada unica ao LLM. Retorna conteudo + tokens para contabilidade."""
    runnable = _build_model(json_mode=json_mode)
    messages = _to_lc_messages(system=system, user=user)
    try:
        result = await asyncio.wait_for(runnable.ainvoke(messages), timeout=30.0)
    except asyncio.TimeoutError as exc:
        logger.warning("agent.llm.timeout", model=settings.AGENT_LLM_MODEL)
        raise RuntimeError("LLM timeout: modelo nao respondeu em 30 segundos.") from exc

    if not isinstance(result, AIMessage):
        logger.exception(
            "agent.llm.complete.bad_response",
            result_type=type(result).__name__,
        )
        raise RuntimeError("Resposta inesperada do LLM (nao e AIMessage)")

    # .content pode vir como string ou como lista de blocos (Anthropic com
    # content blocks). Normalizamos concatenando os textos.
    content: str
    if isinstance(result.content, str):
        content = result.content
    elif isinstance(result.content, list):
        parts: list[str] = []
        for block in result.content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        content = "".join(parts)
    else:
        content = str(result.content or "")

    prompt_tokens, completion_tokens, model = _extract_usage(result)
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


def _lc_message_from_dict(raw: dict[str, Any]) -> SystemMessage | HumanMessage | AIMessage:
    """Converte um dict role/content (estilo OpenAI) em mensagem LangChain.

    O report_node monta seu proprio historico com dicts; mantemos a compat
    aceitando esse formato em llm_stream.
    """
    role = str(raw.get("role") or "user").lower()
    content = raw.get("content") or ""
    if role == "system":
        return SystemMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


async def llm_stream(
    *,
    messages: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Streaming de texto simples. Usado por report_node para emitir delta SSE.

    Retorna os pedacos de texto a medida que o provider os envia. O trace do
    LangSmith captura toda a resposta consolidada automaticamente (o tracer
    agrega os chunks no on_chat_model_end).
    """
    runnable = _build_model(json_mode=False)
    lc_messages = [_lc_message_from_dict(m) for m in messages]

    try:
        stream = runnable.astream(lc_messages)
        async for chunk in stream:
            # AIMessageChunk.content pode ser string ou lista de blocos; na
            # pratica OpenAI/Anthropic retornam string nos chunks de delta.
            content = getattr(chunk, "content", None)
            if not content:
                continue
            if isinstance(content, str):
                yield content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str) and block:
                        yield block
                    elif (
                        isinstance(block, dict)
                        and block.get("type") == "text"
                        and block.get("text")
                    ):
                        yield str(block["text"])
    except asyncio.TimeoutError as exc:
        logger.warning("agent.llm.stream.timeout", model=settings.AGENT_LLM_MODEL)
        raise RuntimeError(
            "LLM stream timeout: modelo nao respondeu em 30 segundos."
        ) from exc
