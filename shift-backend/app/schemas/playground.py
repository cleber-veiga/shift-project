"""
Schemas Pydantic para o Playground SQL.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlaygroundQueryRequest(BaseModel):
    """Payload de execução de consulta SQL no Playground."""

    query: str = Field(..., min_length=1, description="Consulta SQL (somente SELECT / WITH)")
    max_rows: int = Field(default=500, ge=1, le=5000, description="Limite de linhas retornadas")


class PlaygroundQueryResponse(BaseModel):
    """Resultado da execução de uma consulta SQL."""

    columns: list[str]
    rows: list[list]  # noqa: UP006  — cada item é uma linha, cada sub-item é o valor da coluna
    row_count: int
    truncated: bool = Field(
        default=False,
        description="True quando o resultado foi cortado pelo max_rows",
    )
    execution_time_ms: int = Field(description="Tempo de execução em milissegundos")


class SchemaColumn(BaseModel):
    """Uma coluna de uma tabela."""

    name: str
    type: str
    nullable: bool = True


class SchemaTable(BaseModel):
    """Uma tabela com suas colunas."""

    name: str
    schema: str | None = Field(
        default=None,
        description="Schema ao qual a tabela pertence. None = schema padrão do usuário conectado.",
    )
    columns: list[SchemaColumn]


class SchemaResponse(BaseModel):
    """Schema completo de uma conexão."""

    tables: list[SchemaTable]
    updated_at: datetime | None = Field(
        default=None,
        description="Data da última atualização do schema (cache ou busca direta)",
    )
    is_cached: bool = Field(
        default=False,
        description="True quando o schema foi carregado do cache local",
    )
