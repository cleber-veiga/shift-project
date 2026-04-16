"""
Decorators de retry baseados em tenacity.

Primitivas de retry reutilizaveis aplicadas a chamadas de I/O (DB, HTTP,
LLM) que podem falhar por causas transitorias.
"""

from __future__ import annotations

import logging
from typing import Callable, TypeVar

from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
)

F = TypeVar("F", bound=Callable[..., object])

# Logger stdlib dedicado para o tenacity (before_sleep_log exige logging.Logger).
# As mensagens continuam passando pela cadeia de processors do structlog
# via logging.basicConfig configurado em app.core.logging.
_retry_logger = logging.getLogger("app.core.retry")


def retry_transient() -> Callable[[F], F]:
    """
    Politica padrao para falhas transitorias: 3 tentativas com backoff
    exponencial (1s, 2s, 4s... ate 10s), relancando a excecao original
    apos esgotar.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(_retry_logger, logging.WARNING),
    )


def retry_with(attempts: int, delay_seconds: float) -> Callable[[F], F]:
    """Factory para decorator com numero fixo de tentativas e delay fixo."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_fixed(delay_seconds),
        before_sleep=before_sleep_log(_retry_logger, logging.WARNING),
    )
