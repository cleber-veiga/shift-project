"""
Core do servidor MCP.

Usa o ``Server`` low-level do SDK (mcp.server.lowlevel). As tools sao
registradas dinamicamente com os schemas retornados por
``/agent-mcp/tools`` — o MCP server nao conhece o catalogo estatico.

Dois transportes estao disponiveis:
  - stdio: para Claude Desktop / Cursor / clientes locais.
  - streamable-http: para integracoes remotas (n8n, Docker).

Ambos reusam a mesma instancia ``Server`` e o mesmo cliente HTTP.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from .approvals import invoke_with_approval
from .client import ShiftBackendClient, ShiftBackendError
from .config import MCPSettings

logger = logging.getLogger("shift_mcp_server.server")

SERVER_NAME = "shift-mcp"
SERVER_VERSION = "0.1.0"


def build_server(client: ShiftBackendClient, settings: MCPSettings) -> Server:
    """Constroi o Server MCP com handlers list_tools / call_tool dinamicos."""
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _handle_list_tools() -> list[mcp_types.Tool]:
        try:
            tools = await client.list_tools()
        except ShiftBackendError as exc:
            logger.error("falha em list_tools: %s", exc)
            return []
        return [_to_mcp_tool(t) for t in tools]

    @server.call_tool()
    async def _handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[mcp_types.TextContent]:
        args = arguments or {}
        text = await invoke_with_approval(
            client, tool=name, arguments=args, settings=settings
        )
        return [mcp_types.TextContent(type="text", text=text)]

    return server


def _to_mcp_tool(entry: dict[str, Any]) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=entry["name"],
        description=entry.get("description", ""),
        inputSchema=entry.get("parameters") or {"type": "object", "properties": {}},
    )


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


def _init_options(server: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


async def run_stdio(server: Server) -> None:
    """Serve via stdio (Claude Desktop, clientes locais)."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, _init_options(server))


async def run_streamable_http(server: Server, *, host: str, port: int) -> None:
    """Serve via HTTP streamable (POST /mcp) — para integracoes remotas.

    Usa StreamableHTTPSessionManager do SDK embrulhado em uma app
    Starlette mini. json_response=True faz o gerenciador responder em
    JSON quando o cliente nao pede stream.
    """
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=True,
        stateless=False,
    )

    async def _asgi_handler(scope: dict, receive: Any, send: Any) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def _lifespan(app):  # type: ignore[no-redef]
        async with manager.run():
            yield

    starlette_app = Starlette(
        debug=False,
        routes=[Mount("/mcp", app=_asgi_handler)],
        lifespan=_lifespan,
    )

    config = uvicorn.Config(
        starlette_app,
        host=host,
        port=port,
        log_level="info",
        lifespan="on",
    )
    server_uvicorn = uvicorn.Server(config)
    await server_uvicorn.serve()


async def run(settings: MCPSettings) -> None:
    """Ponto de entrada async: valida credencial e dispara o transporte."""
    async with ShiftBackendClient(settings) as client:
        # Sanity check: falha rapido se a chave ja nasceu invalida.
        metadata = await client.validate()
        logger.info(
            "chave validada api_key_id=%s allowed_tools=%s",
            metadata.get("api_key_id"),
            metadata.get("allowed_tools"),
        )

        mcp_server = build_server(client, settings)

        if settings.shift_mcp_transport == "stdio":
            await run_stdio(mcp_server)
        else:
            await run_streamable_http(
                mcp_server,
                host=settings.shift_mcp_host,
                port=settings.shift_mcp_port,
            )


def run_sync(settings: MCPSettings) -> None:
    """Wrapper sincrono usado pelo CLI."""
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        logger.info("encerrado pelo usuario (SIGINT)")
