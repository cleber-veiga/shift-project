"""
Schemas Pydantic para o Playground SQL.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    primary_key: bool = Field(
        default=False,
        description="True quando a coluna faz parte da chave primária.",
    )


class ForeignKey(BaseModel):
    """Relacionamento de chave estrangeira entre tabelas."""

    columns: list[str] = Field(description="Colunas locais que compõem a FK")
    ref_table: str = Field(description="Tabela referenciada")
    ref_columns: list[str] = Field(description="Colunas referenciadas na outra tabela")
    ref_schema: str | None = Field(default=None, description="Schema da tabela referenciada")


class SchemaTable(BaseModel):
    """Uma tabela com suas colunas."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    schema_name: str | None = Field(
        default=None,
        alias="schema",
        description="Schema ao qual a tabela pertence. None = schema padrão do usuário conectado.",
    )
    columns: list[SchemaColumn]
    foreign_keys: list[ForeignKey] = Field(
        default_factory=list,
        description="Chaves estrangeiras saindo desta tabela.",
    )
    row_count_estimate: int | None = Field(
        default=None,
        description="Estimativa de linhas (via estatísticas do banco). None quando não disponível.",
    )


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
