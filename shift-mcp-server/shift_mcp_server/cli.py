"""
CLI do shift-mcp-server.

Uso:
    shift-mcp-server run                   # transporte definido por env
    shift-mcp-server run --transport stdio
    shift-mcp-server run --transport streamable-http --port 8765
    shift-mcp-server validate              # so testa a chave e sai
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

import click

from .client import ShiftBackendClient, ShiftBackendError
from .config import MCPSettings, load_settings
from .server import run_sync


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        stream=sys.stderr,  # stdout e reservado ao transporte stdio MCP
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Log em DEBUG.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Ponte MCP para o Platform Agent do Shift."""
    _configure_logging(verbose)
    try:
        ctx.obj = load_settings()
    except Exception as exc:  # ValidationError em envs faltantes
        click.echo(f"Configuracao invalida: {exc}", err=True)
        sys.exit(2)


@cli.command("run")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"], case_sensitive=False),
    default=None,
    help="Sobrescreve SHIFT_MCP_TRANSPORT.",
)
@click.option("--host", default=None, help="Sobrescreve host HTTP.")
@click.option("--port", type=int, default=None, help="Sobrescreve porta HTTP.")
@click.pass_obj
def run_cmd(
    settings: MCPSettings,
    transport: Literal["stdio", "streamable-http"] | None,
    host: str | None,
    port: int | None,
) -> None:
    """Inicia o servidor MCP no transporte configurado."""
    updates: dict = {}
    if transport is not None:
        updates["shift_mcp_transport"] = transport.lower()
    if host is not None:
        updates["shift_mcp_host"] = host
    if port is not None:
        updates["shift_mcp_port"] = port
    effective = settings.model_copy(update=updates) if updates else settings
    run_sync(effective)


@cli.command("validate")
@click.pass_obj
def validate_cmd(settings: MCPSettings) -> None:
    """Valida a chave contra o backend e imprime o escopo."""
    import asyncio

    async def _run() -> int:
        async with ShiftBackendClient(settings) as client:
            try:
                metadata = await client.validate()
            except ShiftBackendError as exc:
                click.echo(f"Chave invalida: {exc}", err=True)
                return 1
            click.echo(
                f"OK — api_key_id={metadata.get('api_key_id')} "
                f"workspace={metadata.get('workspace_id')} "
                f"tools={metadata.get('allowed_tools')} "
                f"approval={metadata.get('require_human_approval')}"
            )
            return 0

    sys.exit(asyncio.run(_run()))


def main() -> None:
    cli(standalone_mode=True)


if __name__ == "__main__":
    main()
