"""
Testes da politica de retry (Fase 5a) — ``_run_with_retry`` no runner.

Exercitam a logica de retry isoladamente, sem subir workflow real:
cada teste monta uma ``attempt_factory`` que retorna coroutines frescas
e verifica que o retry respeita ``max_attempts``, ``retry_on`` e
``backoff_strategy``. ``asyncio.sleep`` e monkeypatchado para medir
atrasos sem de fato bloquear o loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from app.orchestration.flows.dynamic_runner import (
    _compute_backoff,
    _parse_retry_policy,
    _run_with_retry,
)
from app.schemas.workflow import RetryPolicyConfig
from app.services.workflow.nodes.exceptions import NodeProcessingError


@pytest.fixture
def logger() -> logging.Logger:
    log = logging.getLogger("test_retry")
    log.setLevel(logging.CRITICAL)
    return log


class _Sink:
    """Coletor de eventos para inspecao."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, ev: dict[str, Any]) -> None:
        self.events.append(ev)


def _factory(impl):
    """Envelopa ``impl`` num factory que produz uma coroutine fresca por attempt."""

    def build():
        return impl()

    return build


# ---------------------------------------------------------------------------
# 1. _parse_retry_policy — dict valido, None e lixo
# ---------------------------------------------------------------------------


class TestParseRetryPolicy:
    def test_accepts_valid_dict(self) -> None:
        policy = _parse_retry_policy(
            {"max_attempts": 3, "backoff_strategy": "fixed", "backoff_seconds": 0.5}
        )
        assert isinstance(policy, RetryPolicyConfig)
        assert policy.max_attempts == 3
        assert policy.backoff_strategy == "fixed"

    def test_none_returns_none(self) -> None:
        assert _parse_retry_policy(None) is None

    def test_invalid_returns_none(self) -> None:
        assert _parse_retry_policy({"max_attempts": 99}) is None  # > 10
        assert _parse_retry_policy("not a dict") is None
        assert _parse_retry_policy(123) is None

    def test_accepts_instance(self) -> None:
        policy = RetryPolicyConfig(max_attempts=2)
        assert _parse_retry_policy(policy) is policy


# ---------------------------------------------------------------------------
# 2. _compute_backoff — 3 estrategias
# ---------------------------------------------------------------------------


class TestComputeBackoff:
    def test_none_always_zero(self) -> None:
        pol = RetryPolicyConfig(max_attempts=5, backoff_strategy="none", backoff_seconds=1.0)
        assert _compute_backoff(pol, 1) == 0.0
        assert _compute_backoff(pol, 4) == 0.0

    def test_fixed_is_constant(self) -> None:
        pol = RetryPolicyConfig(max_attempts=5, backoff_strategy="fixed", backoff_seconds=2.5)
        assert _compute_backoff(pol, 1) == 2.5
        assert _compute_backoff(pol, 3) == 2.5

    def test_exponential_doubles_each_attempt(self) -> None:
        pol = RetryPolicyConfig(
            max_attempts=5, backoff_strategy="exponential", backoff_seconds=1.0
        )
        # attempt=1 -> 1 * 2^0 = 1
        # attempt=2 -> 1 * 2^1 = 2
        # attempt=3 -> 1 * 2^2 = 4
        assert _compute_backoff(pol, 1) == 1.0
        assert _compute_backoff(pol, 2) == 2.0
        assert _compute_backoff(pol, 3) == 4.0


# ---------------------------------------------------------------------------
# 3. Retry succeeds on 2nd attempt
# ---------------------------------------------------------------------------


class TestRetrySucceedsOnSecondAttempt:
    def test_second_attempt_wins(self, logger, monkeypatch) -> None:
        async def _noop(*_a, **_k):
            return None

        monkeypatch.setattr(asyncio, "sleep", _noop)

        calls = 0

        async def impl():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise NodeProcessingError("falha intermitente")
            return {"status": "success", "data": "ok"}

        sink = _Sink()
        policy = RetryPolicyConfig(
            max_attempts=3, backoff_strategy="fixed", backoff_seconds=0.1
        )

        result = asyncio.run(
            _run_with_retry(
                node_id="n1",
                attempt_factory=_factory(impl),
                policy=policy,
                timeout=5.0,
                logger=logger,
                event_sink=sink,
                execution_id="exec-1",
                node_type_for_event="mapper",
                label_for_event="Map",
            )
        )

        assert result == {"status": "success", "data": "ok"}
        assert calls == 2
        # Um node_retry deve ter sido emitido (apos a 1a falha).
        retry_events = [e for e in sink.events if e["type"] == "node_retry"]
        assert len(retry_events) == 1
        assert retry_events[0]["attempt"] == 1
        assert retry_events[0]["max_attempts"] == 3


# ---------------------------------------------------------------------------
# 4. Retry exhausted — propaga excecao apos last attempt
# ---------------------------------------------------------------------------


class TestRetryExhausted:
    def test_raises_after_max_attempts(self, logger, monkeypatch) -> None:
        async def _noop(*_a, **_k):
            return None

        monkeypatch.setattr(asyncio, "sleep", _noop)

        calls = 0

        async def impl():
            nonlocal calls
            calls += 1
            raise NodeProcessingError(f"boom #{calls}")

        sink = _Sink()
        policy = RetryPolicyConfig(
            max_attempts=3, backoff_strategy="none", backoff_seconds=0.1
        )

        with pytest.raises(NodeProcessingError, match="boom #3"):
            asyncio.run(
                _run_with_retry(
                    node_id="n1",
                    attempt_factory=_factory(impl),
                    policy=policy,
                    timeout=5.0,
                    logger=logger,
                    event_sink=sink,
                    execution_id="exec-1",
                    node_type_for_event="mapper",
                    label_for_event="Map",
                )
            )

        assert calls == 3
        retry_events = [e for e in sink.events if e["type"] == "node_retry"]
        # 2 eventos: apos tentativa 1 e 2 (a 3a exaure e propaga sem novo evento).
        assert len(retry_events) == 2


# ---------------------------------------------------------------------------
# 5. retry_on filter — erro que nao bate filtro nao faz retry
# ---------------------------------------------------------------------------


class TestRetryOnFilter:
    def test_non_matching_error_aborts_without_retry(self, logger) -> None:
        calls = 0

        async def impl():
            nonlocal calls
            calls += 1
            raise NodeProcessingError("erro de validacao de schema")

        policy = RetryPolicyConfig(
            max_attempts=5,
            backoff_strategy="none",
            backoff_seconds=0.1,
            retry_on=["timeout", "network"],  # nada casa com "validacao"
        )

        with pytest.raises(NodeProcessingError, match="validacao"):
            asyncio.run(
                _run_with_retry(
                    node_id="n1",
                    attempt_factory=_factory(impl),
                    policy=policy,
                    timeout=5.0,
                    logger=logger,
                    event_sink=None,
                    execution_id=None,
                    node_type_for_event="http",
                    label_for_event="HTTP",
                )
            )

        assert calls == 1  # nenhum retry

    def test_matching_error_does_retry(self, logger, monkeypatch) -> None:
        async def _noop(*_a, **_k):
            return None

        monkeypatch.setattr(asyncio, "sleep", _noop)

        calls = 0

        async def impl():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise NodeProcessingError("connection timeout apos 5s")
            return {"status": "success"}

        policy = RetryPolicyConfig(
            max_attempts=5,
            backoff_strategy="none",
            backoff_seconds=0.1,
            retry_on=["timeout"],
        )

        result = asyncio.run(
            _run_with_retry(
                node_id="n1",
                attempt_factory=_factory(impl),
                policy=policy,
                timeout=5.0,
                logger=logger,
                event_sink=None,
                execution_id=None,
                node_type_for_event="http",
                label_for_event="HTTP",
            )
        )

        assert result == {"status": "success"}
        assert calls == 3


# ---------------------------------------------------------------------------
# 6. Exponential backoff — atrasos crescentes entre tentativas
# ---------------------------------------------------------------------------


class TestExponentialBackoffDelays:
    def test_sleeps_are_exponential(self, logger, monkeypatch) -> None:
        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async def impl():
            raise NodeProcessingError("sempre falha")

        policy = RetryPolicyConfig(
            max_attempts=4,
            backoff_strategy="exponential",
            backoff_seconds=0.5,
        )

        with pytest.raises(NodeProcessingError):
            asyncio.run(
                _run_with_retry(
                    node_id="n1",
                    attempt_factory=_factory(impl),
                    policy=policy,
                    timeout=5.0,
                    logger=logger,
                    event_sink=None,
                    execution_id=None,
                    node_type_for_event="mapper",
                    label_for_event="Map",
                )
            )

        # 4 tentativas, 3 sleeps entre elas: 0.5, 1.0, 2.0.
        assert sleep_calls == [0.5, 1.0, 2.0]


# ---------------------------------------------------------------------------
# 7. Sem politica (policy=None) — tentativa unica, backward compat
# ---------------------------------------------------------------------------


class TestNoPolicyIsSingleAttempt:
    def test_single_attempt_without_policy(self, logger) -> None:
        calls = 0

        async def impl():
            nonlocal calls
            calls += 1
            raise NodeProcessingError("falha unica")

        with pytest.raises(NodeProcessingError, match="falha unica"):
            asyncio.run(
                _run_with_retry(
                    node_id="n1",
                    attempt_factory=_factory(impl),
                    policy=None,
                    timeout=5.0,
                    logger=logger,
                    event_sink=None,
                    execution_id=None,
                    node_type_for_event="mapper",
                    label_for_event="Map",
                )
            )

        assert calls == 1
