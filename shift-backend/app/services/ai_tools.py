"""
Tools disponíveis para o Assistente SQL.

Todas as tools são read-only e reutilizam playground_service para
introspecção de schema (cache) e execução de queries (SELECT-only).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.playground import SchemaResponse
from app.services.playground_service import playground_service

# ---------------------------------------------------------------------------
# Schemas das tools (formato OpenAI function calling — LiteLLM converte)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": (
                "Lista as tabelas disponiveis no banco de dados. "
                "Use para descobrir quais tabelas existem."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": (
                            "Filtro opcional por nome (substring, case-insensitive)"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": (
                "Retorna todas as colunas, tipos e nullable de uma tabela específica. "
                "Use para entender a estrutura exata antes de gerar SQL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Nome exato da tabela",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_columns",
            "description": (
                "Busca colunas em todas as tabelas cujo nome contenha a keyword. "
                "Use para encontrar onde um dado especifico esta armazenado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Palavra a buscar no nome das colunas (case-insensitive)",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_select",
            "description": (
                "Executa uma consulta SELECT no banco e retorna ate 20 linhas de resultado. "
                "Use com moderacao — prefira explorar o schema antes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Consulta SQL (somente SELECT ou WITH)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Implementação das tools
# ---------------------------------------------------------------------------

_MAX_LIST_TABLES = 60
_MAX_FIND_COLUMNS = 40
_EXECUTE_MAX_ROWS = 20


def _list_tables(schema: SchemaResponse, name_filter: str | None = None) -> str:
    """Lista tabelas do schema cacheado, com filtro opcional."""
    tables = schema.tables
    if name_filter:
        kw = name_filter.lower()
        tables = [t for t in tables if kw in t.name.lower()]

    if not tables:
        return "Nenhuma tabela encontrada."

    total = len(tables)
    truncated = total > _MAX_LIST_TABLES
    lines = [
        f"- {t.name} ({len(t.columns)} colunas)"
        for t in tables[:_MAX_LIST_TABLES]
    ]

    header = f"{total} tabelas encontradas"
    if truncated:
        header += f" (exibindo primeiras {_MAX_LIST_TABLES})"
    header += ":"

    return header + "\n" + "\n".join(lines)


def _describe_table(schema: SchemaResponse, table_name: str) -> str:
    """Retorna colunas detalhadas de uma tabela."""
    table_lower = table_name.lower()
    table = next(
        (t for t in schema.tables if t.name.lower() == table_lower),
        None,
    )
    if table is None:
        return f"Tabela '{table_name}' nao encontrada no schema."

    lines = [f"Tabela: {table.name} ({len(table.columns)} colunas)\n"]
    for col in table.columns:
        nullable = "NULL" if col.nullable else "NOT NULL"
        lines.append(f"  - {col.name}: {col.type} ({nullable})")

    return "\n".join(lines)


def _find_columns(schema: SchemaResponse, keyword: str) -> str:
    """Busca colunas por nome em todas as tabelas."""
    kw = keyword.lower()
    matches: list[str] = []
    for table in schema.tables:
        for col in table.columns:
            if kw in col.name.lower():
                matches.append(f"- {table.name}.{col.name} ({col.type})")
                if len(matches) >= _MAX_FIND_COLUMNS:
                    break
        if len(matches) >= _MAX_FIND_COLUMNS:
            break

    if not matches:
        return f"Nenhuma coluna com '{keyword}' encontrada."

    header = f"{len(matches)} colunas encontradas"
    if len(matches) == _MAX_FIND_COLUMNS:
        header += f" (limitado a {_MAX_FIND_COLUMNS})"
    header += ":"

    return header + "\n" + "\n".join(matches)


async def _execute_select(
    db: AsyncSession,
    connection_id: UUID,
    query: str,
) -> str:
    """Executa SELECT via playground_service (segurança já validada lá)."""
    try:
        result = await playground_service.execute_query(
            db,
            connection_id,
            query=query,
            max_rows=_EXECUTE_MAX_ROWS,
        )
    except ValueError as exc:
        return f"Erro na consulta: {exc}"

    if not result.columns:
        return "A consulta retornou sem colunas."

    lines = [" | ".join(result.columns)]
    lines.append("-" * len(lines[0]))
    for row in result.rows:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

    summary = f"\n\n{result.row_count} linhas retornadas"
    if result.truncated:
        summary += f" (truncado em {_EXECUTE_MAX_ROWS})"
    summary += f" em {result.execution_time_ms}ms."

    return "\n".join(lines) + summary


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    db: AsyncSession,
    connection_id: UUID,
    schema: SchemaResponse,
) -> str:
    """Executa a tool pelo nome e retorna o resultado como string."""
    if name == "list_tables":
        return _list_tables(schema, arguments.get("name_filter"))
    if name == "describe_table":
        return _describe_table(schema, arguments.get("table_name", ""))
    if name == "find_columns":
        return _find_columns(schema, arguments.get("keyword", ""))
    if name == "execute_select":
        return await _execute_select(db, connection_id, arguments.get("query", ""))
    return f"Tool desconhecida: {name}"


def parse_tool_arguments(raw: str | dict) -> dict[str, Any]:
    """Converte argumentos da tool (podem vir como string JSON ou dict)."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
