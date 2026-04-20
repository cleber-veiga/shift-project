"""
Cliente HTTP para os endpoints /agent-mcp/* do backend Shift.

Mantem um httpx.AsyncClient compartilhado com Authorization injetado.
Cada metodo devolve o corpo ja tipado como dict — o servidor MCP nao
precisa conhecer os modelos Pydantic do backend.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any
from uuid import UUID

import httpx

from .config import MCPSettings


class ShiftBackendError(Exception):
    """Erro HTTP ou semantico retornado pelo backend."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"[{status_code}] {detail}")
        self.status_code = status_code
        self.detail = detail


class ShiftBackendClient:
    """Wrapper fino sobre httpx.AsyncClient com retry-friendly errors."""

    def __init__(self, settings: MCPSettings) -> None:
        self._settings = settings
        base_url = str(settings.shift_backend_url).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=settings.shift_mcp_request_timeout,
            headers={
                "Authorization": f"Bearer {settings.shift_api_key.get_secret_value()}",
                "Accept": "application/json",
                "User-Agent": "shift-mcp-server/0.1.0",
            },
        )

    async def __aenter__(self) -> "ShiftBackendClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- rotas -------------------------------------------------------------

    async def validate(self) -> dict[str, Any]:
        """POST /agent-mcp/validate → metadados do token."""
        return await self._post("/agent-mcp/validate")

    async def list_tools(self) -> list[dict[str, Any]]:
        """GET /agent-mcp/tools → tools permitidas por esta chave."""
        body = await self._get("/agent-mcp/tools")
        return list(body.get("tools", []))

    async def execute(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        approval_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """POST /agent-mcp/execute → resultado ou pending_approval."""
        payload: dict[str, Any] = {"tool": tool, "arguments": arguments}
        if approval_id is not None:
            payload["approval_id"] = str(approval_id)
        return await self._post("/agent-mcp/execute", json=payload)

    async def get_approval(self, approval_id: UUID | str) -> dict[str, Any]:
        """GET /agent-mcp/approvals/{id} → status atual (polling)."""
        return await self._get(f"/agent-mcp/approvals/{approval_id}")

    # -- helpers -----------------------------------------------------------

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:  # timeout, connection, etc.
            raise ShiftBackendError(599, f"erro de rede: {exc}") from exc
        return self._unwrap(response)

    async def _post(
        self, path: str, *, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=json)
        except httpx.HTTPError as exc:
            raise ShiftBackendError(599, f"erro de rede: {exc}") from exc
        return self._unwrap(response)

    @staticmethod
    def _unwrap(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            detail: str
            try:
                body = response.json()
                detail = str(body.get("detail", response.text))
            except ValueError:
                detail = response.text or response.reason_phrase
            raise ShiftBackendError(response.status_code, detail)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ShiftBackendError(
                response.status_code, f"resposta nao-JSON: {exc}"
            ) from exc
