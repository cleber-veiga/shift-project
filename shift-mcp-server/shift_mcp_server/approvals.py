"""
Fluxo de aprovacao: quando o backend devolve pending_approval, o MCP
server polla /approvals/{id} ate o status virar approved/rejected/expired
ou estourar o timeout configurado.

A funcao `invoke_with_approval` encapsula o ciclo completo (primeira
chamada + polling + re-execucao com approval_id) e devolve o texto
para ser embrulhado num TextContent pelo handler do MCP.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .client import ShiftBackendClient, ShiftBackendError
from .config import MCPSettings

logger = logging.getLogger("shift_mcp_server.approvals")


class ApprovalTimeoutError(RuntimeError):
    """Esgotou o tempo aguardando decisao humana."""


class ApprovalRejectedError(RuntimeError):
    """Humano rejeitou a operacao."""


class ApprovalExpiredError(RuntimeError):
    """Aprovacao expirou no backend antes de ser aprovada."""


async def invoke_with_approval(
    client: ShiftBackendClient,
    *,
    tool: str,
    arguments: dict[str, Any],
    settings: MCPSettings,
) -> str:
    """Executa uma tool via bridge MCP, tratando approval automaticamente.

    Retorna sempre texto — em caso de erro, uma descricao amigavel do
    motivo (rejeicao, timeout, erro HTTP). Nao re-levanta excecoes em
    fluxo de negocio porque o MCP SDK espera uma resposta textual.
    """
    try:
        first = await client.execute(tool=tool, arguments=arguments)
    except ShiftBackendError as exc:
        return _format_http_error(exc, tool)

    status = first.get("status")
    if status == "success":
        return first.get("result") or "(sem saida)"
    if status == "error":
        return first.get("error") or first.get("result") or "Erro desconhecido."
    if status != "pending_approval":
        return f"Resposta inesperada do backend: {first!r}"

    approval_id = first.get("approval_id")
    if not approval_id:
        return "Backend sinalizou pending_approval sem approval_id."

    logger.info(
        "aguardando aprovacao humana tool=%s approval_id=%s", tool, approval_id
    )
    try:
        await _wait_for_approval(client, approval_id=approval_id, settings=settings)
    except ApprovalRejectedError as exc:
        return f"Operacao rejeitada: {exc}"
    except ApprovalExpiredError:
        return "Aprovacao expirou sem decisao humana."
    except ApprovalTimeoutError:
        return (
            f"Timeout ({settings.shift_mcp_approval_timeout:.0f}s) aguardando "
            f"aprovacao humana. A operacao permanece pendente no backend; "
            f"use approval_id={approval_id} para consulta."
        )
    except ShiftBackendError as exc:
        return _format_http_error(exc, tool)

    # Reexecuta com approval_id — backend revalida tool/arguments contra o plano.
    try:
        second = await client.execute(
            tool=tool, arguments=arguments, approval_id=approval_id
        )
    except ShiftBackendError as exc:
        return _format_http_error(exc, tool)

    if second.get("status") == "success":
        return second.get("result") or "(sem saida)"
    return second.get("error") or second.get("result") or "Erro desconhecido."


async def _wait_for_approval(
    client: ShiftBackendClient,
    *,
    approval_id: str,
    settings: MCPSettings,
) -> None:
    deadline = time.monotonic() + settings.shift_mcp_approval_timeout
    interval = settings.shift_mcp_approval_poll_interval

    while True:
        body = await client.get_approval(approval_id)
        status = body.get("status")
        if status == "approved":
            return
        if status == "rejected":
            raise ApprovalRejectedError(
                body.get("rejection_reason") or "sem motivo fornecido"
            )
        if status == "expired":
            raise ApprovalExpiredError()
        if time.monotonic() >= deadline:
            raise ApprovalTimeoutError()
        await asyncio.sleep(interval)


def _format_http_error(exc: ShiftBackendError, tool: str) -> str:
    return (
        f"Falha ao executar '{tool}' no backend "
        f"(HTTP {exc.status_code}): {exc.detail}"
    )
