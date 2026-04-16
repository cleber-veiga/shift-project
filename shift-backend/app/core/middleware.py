"""
Middlewares centrais da aplicacao.

Contem correlation ID (request_id) propagado via structlog contextvars,
acessivel em todo log emitido durante o ciclo de vida de uma request —
inclusive por tasks de background spawnadas dentro dela (asyncio copia
o contexto ao criar tasks).
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Injeta ``request_id`` em todos os logs emitidos durante a request.

    - Le o header ``X-Request-ID`` (se vier de um proxy/gateway upstream).
    - Senao, gera um UUID4 novo.
    - Propaga via ``structlog.contextvars`` — qualquer logger.info() dentro
      do request handler inclui ``request_id`` automaticamente.
    - Limpa os contextvars ao final para nao vazar entre requests.
    - Ecoa o ID no header da resposta para o cliente correlacionar.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())

        # Limpa primeiro: em caso de pool de workers reutilizando contextos
        # (ex.: gunicorn+uvicorn workers), garante que nao ha lixo anterior.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
        )

        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
