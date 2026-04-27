"""Rate limiting de replay manual de dead-letters (Tarefa 5 6.2/6.3).

Por que existe
--------------
``POST /webhook-subscriptions/{id}/dead-letters/{dl_id}/replay`` permite
operador re-disparar um dead-letter. Sem limite, dois cenarios ruins:

1. Cliente nervoso aperta o botao 100 vezes por nervosismo / DDoSa o
   proprio servidor de webhook destino.
2. Manager malicioso usa o endpoint como amplificador — escolhe um
   dead-letter pesado e replaya ate exaurir o cliente HTTP.

Limites
-------
Spec:

- Max 1 replay por minuto **por dead-letter** (mesmo dl_id).
- Max 5 replays por hora **por subscription** (todos os dl_ids).

Backend
-------
Usa Redis quando ``RATE_LIMIT_STORAGE_URI`` esta configurado para um
``redis://`` URL — operacoes atomicas via INCR + EXPIRE.

Caso contrario (single replica, dev), usa armazenamento em memoria com
locks por chave. Aceitavel pra single replica; em multi-replica sem
Redis, o limite vira "best effort" — operador deve configurar Redis pra
producao.

Metricas
--------
``webhook_replay_rate_limited_total{workspace_bucket}`` — contador de
429s emitidos. Bucketizamos por hash do workspace_id pra evitar
explosao de cardinalidade (10k workspaces = 10k labels). 16 buckets sao
suficientes pra detectar workspace problematico via dashboards.

Config
------
``WEBHOOK_REPLAY_LIMIT_PER_DEAD_LETTER_SECONDS`` (default 60)
``WEBHOOK_REPLAY_LIMIT_PER_SUBSCRIPTION_PER_HOUR`` (default 5)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from prometheus_client import Counter


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


REPLAY_PER_DL_SECONDS = _int_env(
    "WEBHOOK_REPLAY_LIMIT_PER_DEAD_LETTER_SECONDS", 60,
)
REPLAY_PER_SUB_HOURLY = _int_env(
    "WEBHOOK_REPLAY_LIMIT_PER_SUBSCRIPTION_PER_HOUR", 5,
)


# ---------------------------------------------------------------------------
# Metrica
# ---------------------------------------------------------------------------


WEBHOOK_REPLAY_RATE_LIMITED = Counter(
    "webhook_replay_rate_limited_total",
    "Replays manuais bloqueados por rate limit.",
    ("workspace_bucket",),  # bucketize pra controlar cardinality
)


def _workspace_bucket(workspace_id: UUID | str | None) -> str:
    """Devolve um bucket fixo (16 valores) por workspace_id.

    Mantemos a serie util para alertas (operador ve "bucket 7 esta sendo
    bloqueado") sem virar high-cardinality.
    """
    if workspace_id is None:
        return "unknown"
    return f"b{abs(hash(str(workspace_id))) % 16:02d}"


# ---------------------------------------------------------------------------
# Excecao publica
# ---------------------------------------------------------------------------


class ReplayRateLimitExceeded(Exception):
    """Levantada quando o operador excede o rate limit do replay.

    ``retry_after_seconds``: quantos segundos o caller deve esperar antes
    de tentar de novo. FastAPI usa esse valor no header ``Retry-After``.
    """

    def __init__(self, retry_after_seconds: int, reason: str):
        super().__init__(reason)
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        self.reason = reason


# ---------------------------------------------------------------------------
# Backend em memoria — usado quando nao ha Redis
# ---------------------------------------------------------------------------


@dataclass
class _MemoryBackend:
    """Backend de processo unico — guarda timestamps por chave.

    NAO compartilha entre replicas — em deploys multi-pod, instale
    Redis e configure ``RATE_LIMIT_STORAGE_URI=redis://...``.
    """

    _per_dl_last_seen: dict[str, float] = field(default_factory=dict)
    _per_sub_window: dict[str, deque[float]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def check_per_dl(self, key: str, window_s: int) -> int:
        """Retorna 0 se OK, ou segundos restantes para liberar."""
        async with self._lock:
            now = time.monotonic()
            last = self._per_dl_last_seen.get(key, 0.0)
            remaining = int(window_s - (now - last))
            if remaining > 0:
                return remaining
            self._per_dl_last_seen[key] = now
            return 0

    async def check_per_sub(
        self, key: str, max_per_hour: int,
    ) -> int:
        """Janela deslizante de 1h para a subscription. Retorna 0 ou
        segundos para liberar a vaga mais antiga."""
        async with self._lock:
            now = time.monotonic()
            cutoff = now - 3600
            window = self._per_sub_window.setdefault(key, deque())
            # Drop entradas mais velhas que 1h.
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= max_per_hour:
                # Espera ate a entrada mais velha sair da janela.
                oldest = window[0]
                return max(1, int(3600 - (now - oldest)))
            window.append(now)
            return 0


# ---------------------------------------------------------------------------
# Backend Redis (lazy, opcional)
# ---------------------------------------------------------------------------


class _RedisBackend:
    """Backend redis-py async. Ativado quando ``RATE_LIMIT_STORAGE_URI``
    aponta para ``redis://``.

    Operacoes atomicas:
    - per_dl: ``SET key value NX EX <window>``. Se SET retornou OK,
      e a primeira ocorrencia na janela. Se nao, calcula TTL restante.
    - per_sub: usa ZSET com timestamps. ``ZREMRANGEBYSCORE`` drop
      antigos, depois ``ZCARD``; se >= max, calcula tempo ate o
      mais velho cair fora.
    """

    def __init__(self, url: str):
        try:
            import redis.asyncio as aioredis  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"RATE_LIMIT_STORAGE_URI={url} requer pacote redis-py: {exc}"
            )
        self._client = aioredis.from_url(url, decode_responses=True)

    async def check_per_dl(self, key: str, window_s: int) -> int:
        # SET NX retorna True se a chave era inexistente. Se False,
        # ja havia uma replay ativa.
        was_set = await self._client.set(key, "1", ex=window_s, nx=True)
        if was_set:
            return 0
        ttl = await self._client.ttl(key)
        return int(ttl) if ttl > 0 else 1

    async def check_per_sub(self, key: str, max_per_hour: int) -> int:
        # Janela deslizante via ZSET com timestamps como scores.
        import time as _time
        now_ms = int(_time.time() * 1000)
        cutoff = now_ms - 3600 * 1000
        # Pipeline (atomico): drop antigos, conta, eventualmente adiciona.
        async with self._client.pipeline(transaction=True) as pipe:
            await pipe.zremrangebyscore(key, "-inf", cutoff)
            await pipe.zcard(key)
            results = await pipe.execute()
        count = int(results[1])
        if count >= max_per_hour:
            # Pega timestamp do mais velho pra calcular Retry-After.
            oldest = await self._client.zrange(key, 0, 0, withscores=True)
            if oldest:
                _, ts = oldest[0]
                return max(1, int(3600 - (now_ms - int(ts)) / 1000))
            return 60
        await self._client.zadd(key, {str(now_ms): now_ms})
        await self._client.expire(key, 3600)
        return 0


# ---------------------------------------------------------------------------
# Service publico
# ---------------------------------------------------------------------------


class ReplayLimiter:
    """Aplica os 2 limites do spec sequencialmente.

    Falha rapidamente no primeiro limite que estourar — devolve o
    ``retry_after_seconds`` daquele limite. Caller (rota) converte em
    HTTP 429 com header ``Retry-After``.
    """

    def __init__(self, backend: Any | None = None):
        self._backend = backend or _build_default_backend()

    async def check_and_increment(
        self,
        *,
        subscription_id: UUID,
        dead_letter_id: UUID,
        workspace_id: UUID | None = None,
    ) -> None:
        # 1. Per-dead-letter: 1 replay por minuto pelo mesmo dl_id.
        per_dl_key = f"replay:dl:{dead_letter_id}"
        wait = await self._backend.check_per_dl(per_dl_key, REPLAY_PER_DL_SECONDS)
        if wait > 0:
            WEBHOOK_REPLAY_RATE_LIMITED.labels(
                _workspace_bucket(workspace_id),
            ).inc()
            raise ReplayRateLimitExceeded(
                retry_after_seconds=wait,
                reason="Replay deste dead-letter ja foi disparado recentemente.",
            )

        # 2. Per-subscription: 5 replays por hora.
        per_sub_key = f"replay:sub:{subscription_id}"
        wait = await self._backend.check_per_sub(per_sub_key, REPLAY_PER_SUB_HOURLY)
        if wait > 0:
            WEBHOOK_REPLAY_RATE_LIMITED.labels(
                _workspace_bucket(workspace_id),
            ).inc()
            raise ReplayRateLimitExceeded(
                retry_after_seconds=wait,
                reason="Limite de replays por subscription excedido na janela de 1h.",
            )


def _build_default_backend() -> Any:
    """Resolve backend a partir do env. Default: memoria.

    ``RATE_LIMIT_STORAGE_URI`` e a mesma env usada por slowapi — reaproveitar
    evita configurar duas URIs distintas em deploy.
    """
    uri = os.getenv("RATE_LIMIT_STORAGE_URI", "").strip()
    if uri.startswith("redis://") or uri.startswith("rediss://"):
        try:
            return _RedisBackend(uri)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "webhook.replay_limiter.redis_init_failed",
                extra={"error": str(exc)},
            )
            # Fallback: memoria. Operador ve o WARN no boot.
    return _MemoryBackend()


# Singleton — compartilhado por toda a aplicacao.
replay_limiter = ReplayLimiter()
