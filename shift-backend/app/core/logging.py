"""
Configuracao central de logging via structlog.

Fornece logger estruturado com campos contextuais (execution_id,
workflow_id, node_id) propagados por contextvars — funciona tanto em
codigo sincrono quanto em tasks async.

Em producao emite JSON; em dev usa ConsoleRenderer colorido. Alterne via
variavel de ambiente ``LOG_FORMAT`` (``console`` | ``json``).
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Any, Iterator

import structlog

from app.core.config import settings


def _build_processors(log_format: str) -> list[Any]:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if log_format == "json":
        shared.append(structlog.processors.JSONRenderer())
    else:
        shared.append(structlog.dev.ConsoleRenderer(colors=True))
    return shared


def _configure() -> None:
    log_format = (settings.LOG_FORMAT or "console").lower()
    log_level_name = (settings.LOG_LEVEL or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=_build_processors(log_format),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Retorna um logger structlog nomeado (equivalente a logging.getLogger)."""
    return structlog.get_logger(name) if name else structlog.get_logger()


@contextmanager
def bind_context(**kwargs: Any) -> Iterator[None]:
    """
    Injeta campos contextuais nos logs emitidos dentro do escopo.

    Uso tipico:
        with bind_context(execution_id=..., workflow_id=..., node_id=...):
            logger.info("evento")

    Valores ``None`` sao descartados para nao poluir os logs.
    """
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    with structlog.contextvars.bound_contextvars(**filtered):
        yield
