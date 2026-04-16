"""
Rate limiting via slowapi (wrapper do ``limits`` sobre Starlette).

Por padrao usa armazenamento em memoria — OK para 1 replica.
Para multi-replica, configure ``RATE_LIMIT_STORAGE_URI=redis://...``
via env: slowapi aceita qualquer URI suportada por ``limits``.

Chave: IP do cliente (via ``X-Forwarded-For`` se atras de proxy, ou
``client.host``). Endpoints sensiveis (login, register, forgot-password)
devem declarar limites explicitos com ``@limiter.limit(...)``.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address


_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_STORAGE_URI,
    # Limite global defensivo — endpoints podem relaxar ou apertar via decorator.
    default_limits=["200/minute"],
    # headers_enabled=False porque exigiria um parametro ``response: Response``
    # em cada rota decorada. O handler de 429 ja adiciona ``Retry-After``, que
    # e o header mais util para o cliente reagir.
    headers_enabled=False,
)
