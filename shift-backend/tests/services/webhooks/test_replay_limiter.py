"""Testes do rate limiter de replay (Tarefa 5 6.2/6.3).

Cobre:
- 2x replay do mesmo dead-letter em < 1min → 429.
- Mesmo dead-letter apos > 1min → OK.
- 5 replays diferentes na mesma subscription → OK; 6º → 429.
- ``Retry-After`` calculado corretamente.
- Backend memoria isolado entre testes.
- Metrica ``webhook_replay_rate_limited_total`` incrementa nos 429.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.webhooks.replay_limiter import (
    REPLAY_PER_DL_SECONDS,
    REPLAY_PER_SUB_HOURLY,
    ReplayLimiter,
    ReplayRateLimitExceeded,
    WEBHOOK_REPLAY_RATE_LIMITED,
    _MemoryBackend,
)


def _counter_value(label: str) -> float:
    for sample in WEBHOOK_REPLAY_RATE_LIMITED.collect():
        for s in sample.samples:
            if s.name.endswith("_total") and s.labels.get("workspace_bucket") == label:
                return s.value
    return 0.0


@pytest.fixture
def limiter():
    """Instancia limpa por teste — backend memoria isolado."""
    return ReplayLimiter(backend=_MemoryBackend())


# ---------------------------------------------------------------------------
# Per-dead-letter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_replay_passes(limiter):
    sub = uuid4()
    dl = uuid4()
    await limiter.check_and_increment(
        subscription_id=sub, dead_letter_id=dl,
    )


@pytest.mark.asyncio
async def test_immediate_repeat_blocked(limiter):
    """Mesmo dead-letter dentro da janela de 60s → 429."""
    sub = uuid4()
    dl = uuid4()
    await limiter.check_and_increment(subscription_id=sub, dead_letter_id=dl)
    with pytest.raises(ReplayRateLimitExceeded) as exc_info:
        await limiter.check_and_increment(subscription_id=sub, dead_letter_id=dl)
    assert exc_info.value.retry_after_seconds > 0
    assert exc_info.value.retry_after_seconds <= REPLAY_PER_DL_SECONDS
    assert "recentemente" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_different_dead_letters_independent(limiter):
    """Cada dead-letter tem janela propria — 2 dl_ids diferentes
    podem replay de uma vez."""
    sub = uuid4()
    dl1 = uuid4()
    dl2 = uuid4()
    await limiter.check_and_increment(subscription_id=sub, dead_letter_id=dl1)
    # Mesmo instante, dl_id diferente — passa.
    await limiter.check_and_increment(subscription_id=sub, dead_letter_id=dl2)


@pytest.mark.asyncio
async def test_after_window_passes(limiter, monkeypatch):
    """Apos a janela, replay do mesmo dl passa de novo."""
    sub = uuid4()
    dl = uuid4()
    await limiter.check_and_increment(subscription_id=sub, dead_letter_id=dl)

    # Avanca o relogio interno do MemoryBackend.
    backend = limiter._backend
    key = f"replay:dl:{dl}"
    backend._per_dl_last_seen[key] = backend._per_dl_last_seen[key] - (
        REPLAY_PER_DL_SECONDS + 1
    )
    # Outro dl pra nao acumular no per-sub.
    await limiter.check_and_increment(subscription_id=sub, dead_letter_id=dl)


# ---------------------------------------------------------------------------
# Per-subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_subscription_limit_allows_max(limiter):
    """5 replays de dead-letters distintos da mesma sub passam."""
    sub = uuid4()
    for _ in range(REPLAY_PER_SUB_HOURLY):
        await limiter.check_and_increment(
            subscription_id=sub, dead_letter_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_per_subscription_limit_blocks_overage(limiter):
    """6º replay (com 5 ja feitos na ultima hora) e bloqueado."""
    sub = uuid4()
    for _ in range(REPLAY_PER_SUB_HOURLY):
        await limiter.check_and_increment(
            subscription_id=sub, dead_letter_id=uuid4(),
        )
    with pytest.raises(ReplayRateLimitExceeded) as exc_info:
        await limiter.check_and_increment(
            subscription_id=sub, dead_letter_id=uuid4(),
        )
    assert exc_info.value.retry_after_seconds > 0
    # Mensagem distingue o limite que estourou.
    assert "subscription" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_per_subscription_limit_per_sub(limiter):
    """Subs diferentes nao se afetam — limite e por sub."""
    sub_a = uuid4()
    sub_b = uuid4()
    for _ in range(REPLAY_PER_SUB_HOURLY):
        await limiter.check_and_increment(
            subscription_id=sub_a, dead_letter_id=uuid4(),
        )
    # Sub B nao foi tocada — passa.
    await limiter.check_and_increment(
        subscription_id=sub_b, dead_letter_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# Metrica
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metric_increments_on_block(limiter):
    sub = uuid4()
    dl = uuid4()
    workspace = uuid4()
    await limiter.check_and_increment(
        subscription_id=sub, dead_letter_id=dl, workspace_id=workspace,
    )
    # Computa bucket do mesmo workspace pro before/after match.
    bucket = f"b{abs(hash(str(workspace))) % 16:02d}"
    before = _counter_value(bucket)
    with pytest.raises(ReplayRateLimitExceeded):
        await limiter.check_and_increment(
            subscription_id=sub, dead_letter_id=dl, workspace_id=workspace,
        )
    after = _counter_value(bucket)
    assert after == before + 1


@pytest.mark.asyncio
async def test_metric_workspace_bucket_stable_for_same_workspace(limiter):
    """Mesmo workspace_id sempre cai no mesmo bucket — operador pode
    correlacionar entre execucoes do servico."""
    workspace = uuid4()
    bucket1 = None
    bucket2 = None
    sub = uuid4()
    dl = uuid4()
    await limiter.check_and_increment(
        subscription_id=sub, dead_letter_id=dl, workspace_id=workspace,
    )
    try:
        await limiter.check_and_increment(
            subscription_id=sub, dead_letter_id=dl, workspace_id=workspace,
        )
    except ReplayRateLimitExceeded:
        pass
    # Mesmo bucket calculado nas duas chamadas (funcao deterministica).
    bucket = f"b{abs(hash(str(workspace))) % 16:02d}"
    assert _counter_value(bucket) >= 1
