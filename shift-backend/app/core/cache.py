"""
Cache TTL em memória para objetos frequentemente acessados (ex.: current_user).

Usa um dict simples com expiração por timestamp — sem dependências externas.
Em produção com múltiplos workers, cada processo terá seu próprio cache,
o que é aceitável para dados imutáveis de curta duração como User.
"""

import time
from typing import TypeVar
from uuid import UUID

T = TypeVar("T")

_DEFAULT_TTL = 30  # segundos


class TTLCache:
    """Cache in-memory com TTL por entrada e limite de tamanho."""

    __slots__ = ("_store", "_ttl", "_max_size")

    def __init__(self, ttl: int = _DEFAULT_TTL, max_size: int = 1024) -> None:
        self._store: dict[UUID, tuple[object, float]] = {}
        self._ttl = ttl
        self._max_size = max_size

    def get(self, key: UUID) -> object | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: UUID, value: object) -> None:
        if len(self._store) >= self._max_size:
            self._evict_expired()
        self._store[key] = (value, time.monotonic() + self._ttl)

    def invalidate(self, key: UUID) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]


user_cache = TTLCache(ttl=30, max_size=1024)
