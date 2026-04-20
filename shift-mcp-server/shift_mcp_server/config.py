"""
Configuracao via variaveis de ambiente.

Todas as variaveis aceitam prefixo SHIFT_MCP_*. Tambem aceitamos
SHIFT_BACKEND_URL e SHIFT_API_KEY sem prefixo por conveniencia — sao
os dois unicos valores obrigatorios para operar.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


TransportKind = Literal["stdio", "streamable-http"]


class MCPSettings(BaseSettings):
    """Configuracao do shift-mcp-server.

    Le de ``.env`` no CWD se presente e de variaveis de ambiente.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",  # aceita SHIFT_BACKEND_URL etc. sem duplicar
        extra="ignore",
        case_sensitive=False,
    )

    # -- conexao com o backend ---------------------------------------------
    shift_backend_url: HttpUrl = Field(
        default=...,
        description="URL base do Shift backend (inclui /api/v1).",
    )
    shift_api_key: SecretStr = Field(
        default=...,
        description="Chave de API Bearer (sk_shift_...).",
    )
    shift_mcp_request_timeout: float = Field(
        default=30.0,
        description="Timeout HTTP por chamada ao backend em segundos.",
    )

    # -- transporte MCP ----------------------------------------------------
    shift_mcp_transport: TransportKind = Field(
        default="stdio",
        description="Transporte MCP: stdio (para Claude Desktop) ou streamable-http.",
    )
    shift_mcp_host: str = Field(
        default="127.0.0.1",
        description="Host do transporte HTTP (ignorado em stdio).",
    )
    shift_mcp_port: int = Field(
        default=8765,
        description="Porta do transporte HTTP (ignorado em stdio).",
    )

    # -- politica de aprovacao ---------------------------------------------
    shift_mcp_approval_poll_interval: float = Field(
        default=2.0,
        ge=0.5,
        le=30.0,
        description="Intervalo entre polls a /approvals/{id}.",
    )
    shift_mcp_approval_timeout: float = Field(
        default=300.0,
        ge=5.0,
        description=(
            "Tempo maximo aguardando aprovacao humana (segundos). "
            "Em timeout, o MCP retorna erro ao cliente sem executar."
        ),
    )


def load_settings() -> MCPSettings:
    """Carrega settings; levanta ValidationError se envs obrigatorias faltarem."""
    return MCPSettings()  # type: ignore[call-arg]
