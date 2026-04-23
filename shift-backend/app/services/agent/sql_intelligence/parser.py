"""Analise estatica de SQL para o Platform Agent.

Usa sqlglot para parse AST-level seguro (sem execucao). Suporta os dialetos
que o Shift usa: oracle, postgres, tsql (SQL Server), mysql, spark.

Funcoes publicas:
  extract_binds(sql)            -> list[BindParam]
  extract_tables(sql)           -> list[TableRef]
  classify_destructiveness(sql) -> Literal['safe','writes','destructive','schema_change']
  split_statements(sql)         -> list[str]

Fallback gracioso: se o sqlglot falhar no parse (SQL invalido ou dialeto
desconhecido), as funcoes retornam resultados vazios/defaults em vez de lancar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import sqlglot
import sqlglot.expressions as exp

# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------

DestructivenessLevel = Literal["safe", "writes", "destructive", "schema_change"]

_INFERRED_INT_RE = re.compile(
    r"^(?:I_|ID_|N_|NUM_|INT_|QTD_|COD_|CD_|PK_|FK_)"
    r"|(?:_ID|_NUM|_COD|_QTD|_COUNT|_QT)$",
    re.IGNORECASE,
)
_INFERRED_DATE_RE = re.compile(
    r"^(?:D_|DT_|DAT_|DATE_)|(?:_DATE|_DT|_DATA|_DTA)$",
    re.IGNORECASE,
)
_INFERRED_DECIMAL_RE = re.compile(
    r"^(?:VL_|VLR_|VALOR_|PRECO_|PRICE_)|(?:_VALOR|_VLR|_PRICE|_AMOUNT)$",
    re.IGNORECASE,
)


def _infer_type(name: str) -> str:
    """Heuristica simples de tipo a partir do nome do parametro."""
    upper = name.upper()
    if _INFERRED_INT_RE.search(upper):
        return "integer"
    if _INFERRED_DATE_RE.search(upper):
        return "date"
    if _INFERRED_DECIMAL_RE.search(upper):
        return "decimal"
    return "string"


@dataclass
class BindParam:
    name: str
    style: str  # "colon" | "at" | "dollar"
    positions: list[int] = field(default_factory=list)
    inferred_type: str = "string"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "style": self.style,
            "positions": self.positions,
            "inferred_type": self.inferred_type,
        }


@dataclass
class TableRef:
    schema: str | None
    table: str
    operation: str  # "READ" | "INSERT" | "UPDATE" | "DELETE" | "TRUNCATE" | "DDL"

    def to_dict(self) -> dict:
        return {"schema": self.schema, "table": self.table, "operation": self.operation}


# ---------------------------------------------------------------------------
# Patterns for bind parameter detection (regex-based because sqlglot strips
# them as named placeholders without preserving position info)
# ---------------------------------------------------------------------------

# Strip block comments /* ... */ and line comments -- ...
_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/", re.MULTILINE)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*\n?")
# Strip single-quoted string literals (replace content with X to preserve structure)
_STRING_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'")

# Oracle/Python style: :name or :NAME
# Negative lookbehind for ':' (excludes ::cast) and '<' (excludes <:type)
# Negative lookahead for ':' (excludes :: forward)
_COLON_BIND_RE = re.compile(r"(?<![:<]):([A-Za-z_][A-Za-z0-9_.]*)(?!:)", re.MULTILINE)

# SQL Server/MySQL style: @name
_AT_BIND_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

# PostgreSQL positional: $1, $2, ...
_DOLLAR_BIND_RE = re.compile(r"\$(\d+)", re.MULTILINE)


def _strip_non_code(sql: str) -> str:
    """Remove comentarios e literais de string para evitar falsos positivos em bind detection."""
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    sql = _STRING_LITERAL_RE.sub("'X'", sql)
    return sql


def extract_binds(sql: str) -> list[BindParam]:
    """Detecta parametros de bind no SQL e infere seus tipos.

    Suporta:
      :PARAM  — Oracle, SQLite, Python DB-API named style
      @param  — SQL Server, MySQL
      $1      — PostgreSQL positional (name = "1", "2", ...)

    Retorna lista ordenada por primeira ocorrencia, sem duplicatas de nome.
    """
    clean = _strip_non_code(sql)
    params: dict[str, BindParam] = {}

    for m in _COLON_BIND_RE.finditer(clean):
        name = m.group(1)
        if name not in params:
            params[name] = BindParam(name=name, style="colon", inferred_type=_infer_type(name))
        params[name].positions.append(m.start())

    for m in _AT_BIND_RE.finditer(clean):
        name = m.group(1)
        if name not in params:
            params[name] = BindParam(name=name, style="at", inferred_type=_infer_type(name))
        params[name].positions.append(m.start())

    dollar_names: set[str] = set()
    for m in _DOLLAR_BIND_RE.finditer(clean):
        name = m.group(1)
        if name not in dollar_names:
            dollar_names.add(name)
            params[f"${name}"] = BindParam(name=name, style="dollar", inferred_type="string")
        params[f"${name}"].positions.append(m.start())

    return sorted(params.values(), key=lambda p: (p.positions[0] if p.positions else 0))


# ---------------------------------------------------------------------------
# Table extraction via sqlglot AST
# ---------------------------------------------------------------------------

_WRITE_NODES = (exp.Insert, exp.Update, exp.Merge)
_DELETE_NODES = (exp.Delete,)
_TRUNCATE_NODES = (exp.TruncateTable,)
_DDL_NODES = (exp.Create, exp.Drop, exp.Alter, exp.Command)


def _operation_for_statement(stmt: exp.Expression) -> str:
    if isinstance(stmt, _DDL_NODES):
        return "DDL"
    if isinstance(stmt, _TRUNCATE_NODES):
        return "TRUNCATE"
    if isinstance(stmt, _DELETE_NODES):
        return "DELETE"
    if isinstance(stmt, _WRITE_NODES):
        if isinstance(stmt, exp.Insert):
            return "INSERT"
        if isinstance(stmt, exp.Update):
            return "UPDATE"
        return "WRITE"
    return "READ"


def extract_tables(sql: str, dialect: str = "oracle") -> list[TableRef]:
    """Extrai referencias de tabelas com a operacao associada.

    Tenta varios dialetos em cascata se o primeiro falhar.
    Retorna lista sem duplicatas (mesma schema+table+operation).
    """
    dialects_to_try = [dialect, "tsql", "mysql", "postgres", ""]
    stmts: list[exp.Expression] = []
    for d in dialects_to_try:
        try:
            stmts = sqlglot.parse(sql, dialect=d or None, error_level=sqlglot.ErrorLevel.IGNORE)
            if stmts:
                break
        except Exception:  # noqa: BLE001
            continue

    if not stmts:
        return []

    seen: set[tuple] = set()
    refs: list[TableRef] = []

    for stmt in stmts:
        if stmt is None:
            continue
        op = _operation_for_statement(stmt)

        if isinstance(stmt, exp.Insert):
            # Target table of INSERT gets the INSERT operation.
            # stmt.this may be a Table (no column list) or Schema (Table + columns).
            target_node = stmt.this
            target_tbl = (
                target_node
                if isinstance(target_node, exp.Table)
                else target_node.find(exp.Table) if target_node else None
            )
            if target_tbl is not None:
                schema_node = target_tbl.args.get("db")
                schema = schema_node.name if schema_node else None
                table_name = target_tbl.name
                if table_name:
                    key = (schema, table_name.upper(), "INSERT")
                    if key not in seen:
                        seen.add(key)
                        refs.append(TableRef(schema=schema, table=table_name, operation="INSERT"))
            # Tables inside the SELECT sub-query get READ operation (not VALUES).
            select_part = stmt.args.get("expression")
            if select_part is not None and isinstance(select_part, exp.Select):
                for tbl in select_part.find_all(exp.Table):
                    schema_node = tbl.args.get("db")
                    schema = schema_node.name if schema_node else None
                    table_name = tbl.name
                    if not table_name:
                        continue
                    key = (schema, table_name.upper(), "READ")
                    if key not in seen:
                        seen.add(key)
                        refs.append(TableRef(schema=schema, table=table_name, operation="READ"))
        else:
            for tbl in stmt.find_all(exp.Table):
                schema_node = tbl.args.get("db")
                schema = schema_node.name if schema_node else None
                table_name = tbl.name
                if not table_name:
                    continue
                key = (schema, table_name.upper(), op)
                if key in seen:
                    continue
                seen.add(key)
                refs.append(TableRef(schema=schema, table=table_name, operation=op))

    return refs


# ---------------------------------------------------------------------------
# Destructiveness classification
# ---------------------------------------------------------------------------

_DESTRUCTIVE_STMT_TYPES = (exp.Delete, exp.TruncateTable)
_SCHEMA_CHANGE_STMT_TYPES = (exp.Create, exp.Drop, exp.Alter)
_WRITE_STMT_TYPES = (exp.Insert, exp.Update, exp.Merge)


def classify_destructiveness(sql: str, dialect: str = "oracle") -> DestructivenessLevel:
    """Classifica o nivel de impacto das instrucoes SQL.

    Returns:
      'safe'         — apenas SELECT / leitura
      'writes'       — INSERT, UPDATE, MERGE
      'destructive'  — DELETE, TRUNCATE
      'schema_change'— CREATE, DROP, ALTER
    """
    dialects_to_try = [dialect, "tsql", "mysql", "postgres", ""]
    stmts: list[exp.Expression] = []
    for d in dialects_to_try:
        try:
            stmts = sqlglot.parse(sql, dialect=d or None, error_level=sqlglot.ErrorLevel.IGNORE)
            if stmts:
                break
        except Exception:  # noqa: BLE001
            continue

    if not stmts:
        # Fallback: regex scan
        upper = sql.upper()
        if re.search(r"\b(DROP|CREATE|ALTER)\b", upper):
            return "schema_change"
        if re.search(r"\b(DELETE|TRUNCATE)\b", upper):
            return "destructive"
        if re.search(r"\b(INSERT|UPDATE|MERGE)\b", upper):
            return "writes"
        return "safe"

    level: DestructivenessLevel = "safe"

    for stmt in stmts:
        if stmt is None:
            continue
        if isinstance(stmt, _SCHEMA_CHANGE_STMT_TYPES):
            return "schema_change"
        if isinstance(stmt, _DESTRUCTIVE_STMT_TYPES):
            level = "destructive"
        elif isinstance(stmt, _WRITE_STMT_TYPES) and level == "safe":
            level = "writes"

    return level


# ---------------------------------------------------------------------------
# Statement splitting
# ---------------------------------------------------------------------------

def split_statements(sql: str, dialect: str = "oracle") -> list[str]:
    """Divide SQL multi-statement em lista de statements individuais.

    Usa sqlglot para split aware de strings/comentarios. Se falhar,
    usa split simples por ponto-e-virgula fora de aspas.
    """
    try:
        tokens = sqlglot.tokenize(sql, dialect=dialect or None)
        # Build statement boundaries from semicolons
        statements: list[str] = []
        start = 0
        full = sql
        for tok in tokens:
            if tok.token_type == sqlglot.TokenType.SEMICOLON:
                chunk = full[start : tok.end].strip()
                if chunk:
                    statements.append(chunk)
                start = tok.end + 1
        remainder = full[start:].strip()
        if remainder:
            statements.append(remainder)
        return statements or [sql.strip()]
    except Exception:  # noqa: BLE001
        # Fallback: naive split (misses semicolons in strings)
        parts = [s.strip() for s in sql.split(";")]
        return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Convenience: full analysis for a sql_script node
# ---------------------------------------------------------------------------

def analyze_sql_script(sql: str, dialect: str = "oracle") -> dict:
    """Retorna analise completa de um sql_script.

    Resultado:
      {
        "binds": [...],           # list[BindParam.to_dict()]
        "tables": [...],          # list[TableRef.to_dict()]
        "destructiveness": "...", # DestructivenessLevel
        "statement_count": int,
        "has_binds": bool,
        "suggested_input_schema": [...],  # [{name, type}] for auto-binding UI
      }
    """
    stmts = split_statements(sql, dialect=dialect)
    binds = extract_binds(sql)
    tables = extract_tables(sql, dialect=dialect)
    level = classify_destructiveness(sql, dialect=dialect)

    suggested = [
        {"name": b.name, "type": b.inferred_type, "style": b.style}
        for b in binds
    ]

    return {
        "binds": [b.to_dict() for b in binds],
        "tables": [t.to_dict() for t in tables],
        "destructiveness": level,
        "statement_count": len(stmts),
        "has_binds": bool(binds),
        "suggested_input_schema": suggested,
    }
