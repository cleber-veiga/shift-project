"""
Tools disponíveis para o Assistente SQL.

Todas as tools são read-only e reutilizam playground_service para
introspecção de schema (cache) e execução de queries (SELECT-only).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.connection import ConnectionType
from app.schemas.playground import SchemaResponse, SchemaTable
from app.services.connection_service import connection_service
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
                "Retorna nome, numero de colunas e estimativa de linhas. "
                "Use name_filter para restringir e offset para paginar em schemas grandes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filtro opcional por nome (substring, case-insensitive)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Deslocamento para paginacao (default 0)",
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
                "Retorna colunas, tipos, nullable, chave primaria, chaves estrangeiras "
                "e estimativa de linhas de uma tabela. Use SEMPRE antes de gerar SQL."
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
                "Use para encontrar onde um dado especifico esta armazenado. "
                "Use offset para paginar quando houver muitos resultados."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Palavra a buscar no nome das colunas (case-insensitive)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Deslocamento para paginacao (default 0)",
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
                "Executa uma consulta SELECT no banco e retorna ate 100 linhas. "
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
    {
        "type": "function",
        "function": {
            "name": "get_sample_rows",
            "description": (
                "Retorna algumas linhas de exemplo de uma tabela. "
                "Muito util para entender o formato e semantica dos dados (enumeracoes, padroes de texto, datas)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Nome exato da tabela",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Quantidade de linhas (1 a 20, default 5)",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_query",
            "description": (
                "Executa EXPLAIN na query e retorna o plano de execucao. "
                "Use para validar se o SQL esta correto e otimizado antes de entregar ao usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Consulta SELECT para explicar",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relationships",
            "description": (
                "Lista chaves estrangeiras de/para uma tabela. "
                "Use para montar JOINs corretos sem chutar colunas de relacionamento."
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
]


# ---------------------------------------------------------------------------
# Limites
# ---------------------------------------------------------------------------

_MAX_LIST_TABLES = 200
_MAX_FIND_COLUMNS = 100
_EXECUTE_MAX_ROWS = 100
_SAMPLE_ROWS_DEFAULT = 5
_SAMPLE_ROWS_MAX = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_row_count(n: int | None) -> str:
    if n is None:
        return ""
    if n >= 1_000_000:
        return f" [~{n / 1_000_000:.1f}M linhas]"
    if n >= 1_000:
        return f" [~{n / 1_000:.1f}k linhas]"
    return f" [~{n} linhas]"


def _find_table(schema: SchemaResponse, table_name: str) -> SchemaTable | None:
    table_lower = table_name.lower()
    return next(
        (t for t in schema.tables if t.name.lower() == table_lower),
        None,
    )


def _qualified(t: SchemaTable) -> str:
    return f"{t.schema_name}.{t.name}" if t.schema_name else t.name


def _parse_offset(val: Any) -> int:
    try:
        n = int(val)
        return max(0, n)
    except (TypeError, ValueError):
        return 0


def _parse_limit(val: Any, default: int, maximum: int) -> int:
    try:
        n = int(val)
        return max(1, min(maximum, n))
    except (TypeError, ValueError):
        return default


def _format_result_table(columns: list[str], rows: list[list]) -> str:
    if not columns:
        return "(sem colunas)"
    lines = [" | ".join(columns)]
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Implementação das tools de schema (síncronas — usam cache)
# ---------------------------------------------------------------------------


def _list_tables(
    schema: SchemaResponse,
    name_filter: str | None = None,
    offset: int = 0,
) -> str:
    tables = schema.tables
    if name_filter:
        kw = name_filter.lower()
        tables = [t for t in tables if kw in t.name.lower()]

    if not tables:
        return "Nenhuma tabela encontrada."

    total = len(tables)
    page = tables[offset : offset + _MAX_LIST_TABLES]
    if not page:
        return f"Offset {offset} alem do total de {total} tabelas."

    lines = [
        f"- {t.name} ({len(t.columns)} colunas){_fmt_row_count(t.row_count_estimate)}"
        for t in page
    ]

    header = f"{total} tabelas"
    if name_filter:
        header += f" com '{name_filter}'"
    end = offset + len(page)
    if total > len(page):
        header += f" — exibindo {offset + 1}-{end}"
        if end < total:
            header += f" (use offset={end} para proxima pagina)"
    header += ":"

    return header + "\n" + "\n".join(lines)


def _describe_table(schema: SchemaResponse, table_name: str) -> str:
    table = _find_table(schema, table_name)
    if table is None:
        return f"Tabela '{table_name}' nao encontrada no schema."

    header = f"Tabela: {_qualified(table)} ({len(table.columns)} colunas)"
    if table.row_count_estimate is not None:
        header += _fmt_row_count(table.row_count_estimate)
    lines = [header, ""]

    for col in table.columns:
        marks = []
        if col.primary_key:
            marks.append("PK")
        if not col.nullable:
            marks.append("NOT NULL")
        suffix = f" [{', '.join(marks)}]" if marks else ""
        lines.append(f"  - {col.name}: {col.type}{suffix}")

    if table.foreign_keys:
        lines.append("")
        lines.append("Chaves estrangeiras:")
        for fk in table.foreign_keys:
            cols = ", ".join(fk.columns)
            ref_cols = ", ".join(fk.ref_columns)
            ref = f"{fk.ref_schema}.{fk.ref_table}" if fk.ref_schema else fk.ref_table
            lines.append(f"  - ({cols}) -> {ref}({ref_cols})")

    return "\n".join(lines)


def _find_columns(schema: SchemaResponse, keyword: str, offset: int = 0) -> str:
    kw = keyword.lower()
    all_matches: list[str] = []
    for table in schema.tables:
        for col in table.columns:
            if kw in col.name.lower():
                pk = " [PK]" if col.primary_key else ""
                all_matches.append(
                    f"- {_qualified(table)}.{col.name} ({col.type}){pk}"
                )

    if not all_matches:
        return f"Nenhuma coluna com '{keyword}' encontrada."

    total = len(all_matches)
    page = all_matches[offset : offset + _MAX_FIND_COLUMNS]
    if not page:
        return f"Offset {offset} alem do total de {total} matches."

    header = f"{total} colunas com '{keyword}'"
    end = offset + len(page)
    if total > len(page):
        header += f" — exibindo {offset + 1}-{end}"
        if end < total:
            header += f" (use offset={end} para proxima pagina)"
    header += ":"

    return header + "\n" + "\n".join(page)


def _get_relationships(schema: SchemaResponse, table_name: str) -> str:
    table = _find_table(schema, table_name)
    if table is None:
        return f"Tabela '{table_name}' nao encontrada no schema."

    lines = [f"Relacionamentos de {_qualified(table)}:"]

    # Outgoing FKs
    if table.foreign_keys:
        lines.append("")
        lines.append("Saindo (esta tabela referencia outras):")
        for fk in table.foreign_keys:
            cols = ", ".join(fk.columns)
            ref_cols = ", ".join(fk.ref_columns)
            ref = f"{fk.ref_schema}.{fk.ref_table}" if fk.ref_schema else fk.ref_table
            lines.append(f"  - ({cols}) -> {ref}({ref_cols})")

    # Incoming FKs (outras tabelas apontando para esta)
    incoming: list[str] = []
    for other in schema.tables:
        if other.name.lower() == table.name.lower() and other.schema_name == table.schema_name:
            continue
        for fk in other.foreign_keys:
            if fk.ref_table.lower() == table.name.lower():
                cols = ", ".join(fk.columns)
                ref_cols = ", ".join(fk.ref_columns)
                incoming.append(
                    f"  - {_qualified(other)}({cols}) -> ({ref_cols})"
                )

    if incoming:
        lines.append("")
        lines.append("Chegando (outras tabelas referenciam esta):")
        lines.extend(incoming)

    if not table.foreign_keys and not incoming:
        return f"{_qualified(table)} nao possui FKs declaradas nem e referenciada por outras tabelas."

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools assíncronas (I/O no banco)
# ---------------------------------------------------------------------------


async def _execute_select(
    db: AsyncSession,
    connection_id: UUID,
    query: str,
) -> str:
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

    body = _format_result_table(result.columns, result.rows)
    summary = f"\n\n{result.row_count} linhas retornadas"
    if result.truncated:
        summary += f" (truncado em {_EXECUTE_MAX_ROWS})"
    summary += f" em {result.execution_time_ms}ms."
    return body + summary


def _sample_query_for_dialect(
    conn_type: str, qualified_name: str, limit: int
) -> str:
    """Monta um SELECT * limitado à sintaxe do dialeto."""
    if conn_type == ConnectionType.oracle.value:
        return f"SELECT * FROM {qualified_name} FETCH FIRST {limit} ROWS ONLY"
    if conn_type == ConnectionType.sqlserver.value:
        return f"SELECT TOP {limit} * FROM {qualified_name}"
    if conn_type == ConnectionType.firebird.value:
        return f"SELECT FIRST {limit} * FROM {qualified_name}"
    # postgresql, mysql
    return f"SELECT * FROM {qualified_name} LIMIT {limit}"


async def _get_sample_rows(
    db: AsyncSession,
    connection_id: UUID,
    schema: SchemaResponse,
    table_name: str,
    limit: int,
) -> str:
    table = _find_table(schema, table_name)
    if table is None:
        return f"Tabela '{table_name}' nao encontrada no schema."

    conn = await connection_service.get(db, connection_id)
    if conn is None:
        return "Conexao nao encontrada."

    qualified = _qualified(table)
    query = _sample_query_for_dialect(conn.type, qualified, limit)

    try:
        result = await playground_service.execute_query(
            db, connection_id, query=query, max_rows=limit
        )
    except ValueError as exc:
        return f"Erro ao amostrar {qualified}: {exc}"

    if not result.columns:
        return f"{qualified} retornou sem colunas."

    body = _format_result_table(result.columns, result.rows)
    return (
        f"Amostra de {qualified} ({result.row_count} linhas, "
        f"{result.execution_time_ms}ms):\n\n{body}"
    )


def _explain_query_for_dialect(conn_type: str, query: str) -> str:
    stripped = query.rstrip().rstrip(";")
    if conn_type == ConnectionType.postgresql.value:
        return f"EXPLAIN {stripped}"
    if conn_type == ConnectionType.mysql.value:
        return f"EXPLAIN {stripped}"
    if conn_type == ConnectionType.sqlserver.value:
        # SET SHOWPLAN requer statement próprio; fallback: retorna estimativa simples
        return f"EXPLAIN {stripped}"
    if conn_type == ConnectionType.oracle.value:
        # Oracle usa EXPLAIN PLAN FOR + SELECT da plan_table; simplificamos
        return f"EXPLAIN PLAN FOR {stripped}"
    if conn_type == ConnectionType.firebird.value:
        # Firebird nao tem EXPLAIN padrao — retornamos a própria query anotada
        return stripped
    return f"EXPLAIN {stripped}"


async def _explain_query(
    db: AsyncSession,
    connection_id: UUID,
    query: str,
) -> str:
    conn = await connection_service.get(db, connection_id)
    if conn is None:
        return "Conexao nao encontrada."

    if conn.type == ConnectionType.firebird.value:
        return "EXPLAIN nao e suportado nativamente no Firebird. Valide a query com execute_select usando um LIMIT pequeno."

    if conn.type == ConnectionType.oracle.value:
        return (
            "Oracle requer EXPLAIN PLAN em 2 passos (plan_table). "
            "Valide a query com execute_select usando ROWNUM <= 1 ou FETCH FIRST 1 ROWS ONLY."
        )

    explain_sql = _explain_query_for_dialect(conn.type, query)
    url = connection_service.build_connection_string(conn)

    def _run() -> tuple[list[str], list[list]]:
        engine = sa.create_engine(
            url, pool_pre_ping=False, pool_size=1, max_overflow=0
        )
        try:
            with engine.connect() as db_conn:
                result = db_conn.execute(sa.text(explain_sql))
                cols = list(result.keys())
                rows = [list(r) for r in result.fetchmany(50)]
                return cols, rows
        finally:
            engine.dispose()

    try:
        cols, rows = await asyncio.to_thread(_run)
    except Exception as exc:
        return f"Erro ao executar EXPLAIN: {exc}"

    body = _format_result_table(
        cols, [[str(v) if v is not None else "" for v in r] for r in rows]
    )
    return f"Plano de execucao:\n\n{body}"


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
        return _list_tables(
            schema,
            arguments.get("name_filter"),
            _parse_offset(arguments.get("offset", 0)),
        )
    if name == "describe_table":
        return _describe_table(schema, arguments.get("table_name", ""))
    if name == "find_columns":
        return _find_columns(
            schema,
            arguments.get("keyword", ""),
            _parse_offset(arguments.get("offset", 0)),
        )
    if name == "execute_select":
        return await _execute_select(db, connection_id, arguments.get("query", ""))
    if name == "get_sample_rows":
        limit = _parse_limit(
            arguments.get("limit"), _SAMPLE_ROWS_DEFAULT, _SAMPLE_ROWS_MAX
        )
        return await _get_sample_rows(
            db, connection_id, schema, arguments.get("table_name", ""), limit
        )
    if name == "explain_query":
        return await _explain_query(db, connection_id, arguments.get("query", ""))
    if name == "get_relationships":
        return _get_relationships(schema, arguments.get("table_name", ""))
    return f"Tool desconhecida: {name}"


def parse_tool_arguments(raw: str | dict) -> dict[str, Any]:
    """Converte argumentos da tool (podem vir como string JSON ou dict)."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
