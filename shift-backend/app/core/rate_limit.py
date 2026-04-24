"""
Rate limiting via slowapi (wrapper do ``limits`` sobre Starlette).

Por padrao usa armazenamento em memoria — OK para 1 replica.
Para multi-replica, configure ``RATE_LIMIT_STORAGE_URI=redis://...``
via env: slowapi aceita qualquer URI suportada por ``limits``.

Endpoints de execucao (POST /execute, POST /test) usam dois key functions:

- ``_user_key_func``: extrai ``user_id`` do JWT (sem DB lookup) — aplicado
  para os limites por usuario (30/min, 500/hora).
- ``_project_key_func``: usa ``project_id`` armazenado em ``request.state``
  pela dependencia ``populate_rate_limit_context`` — aplicado para os limites
  por projeto (100/min, 2000/hora).

A dependencia ``populate_rate_limit_context`` faz um DB lookup lazy (com
cache em memoria por workflow_id) para resolver workflow_id → project_id.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from slowapi import Limiter
from slowapi.util import get_remote_address

if TYPE_CHECKING:
    from fastapi import Request

_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_STORAGE_URI,
    default_limits=["200/minute"],
    headers_enabled=False,
)


# ---------------------------------------------------------------------------
# Cache em memoria: workflow_id -> project_id (imutavel apos criacao)
# ---------------------------------------------------------------------------

_wf_project_cache: dict[str, str] = {}


def _user_key_func(request: "Request") -> str:
    """Extrai user_id do JWT sem fazer DB lookup.

    Usa o header Authorization (Bearer <token>), decodifica sem verificacao
    de assinatura apenas para extrair o ``sub`` (user_id). Fallback para IP.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        import jwt as pyjwt
        token = auth[7:]
        try:
            payload = pyjwt.decode(token, options={"verify_signature": False})
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001
            pass
    return f"ip:{get_remote_address(request)}"


def _project_key_func(request: "Request") -> str:
    """Le project_id de request.state (populado por populate_rate_limit_context).

    Fallback para IP quando o estado nao foi preenchido.
    """
    project_id = getattr(request.state, "rate_limit_project_id", None)
    if project_id:
        return f"project:{project_id}"
    return f"ip:{get_remote_address(request)}"
