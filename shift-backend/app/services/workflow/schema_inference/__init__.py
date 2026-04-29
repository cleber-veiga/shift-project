"""
Schema inference — predição de schema de saída sem executar (Fase 5).

predict_output_schema() retorna a lista de campos que um nó PRODUZ dado:
  - node_type  : tipo do nó
  - config     : config bruta (pode ter ${} ainda não resolvidos → retorna None)
  - input_schemas : dict handle → list[FieldDescriptor] dos upstreams

Implementado para 5 tipos:
  - filter     : passthrough (schema de entrada = schema de saída)
  - mapper     : declarado em config.mappings
  - join       : merge de left + right com resolução de conflito
  - select     : subset declarado em config.columns
  - sql_database : None (requer conexão ativa; schema vem de execução real)

Para todos os demais, retorna None (schema desconhecido até executar).

O endpoint GET /api/v1/workflows/{id}/nodes/{nid}/predicted-schema chama
esta função após rastrear os schemas upstream propagados pelo grafo.

Uso:
    from app.services.workflow.schema_inference import predict_output_schema, FieldDescriptor
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel

# Cache de schemas inferidos para sql_database. Chave: (connection_id, query_hash).
# Limite de 256 entradas em LRU manual via OrderedDict.
_SQL_SCHEMA_CACHE: OrderedDict[tuple[str, str], list["FieldDescriptor"]] = OrderedDict()
_SQL_SCHEMA_CACHE_MAX = 256


class FieldDescriptor(BaseModel):
    """Descreve um campo de saída de um nó."""

    name: str
    data_type: str   # SQL type (VARCHAR, INTEGER, DOUBLE, BOOLEAN, DATE, …)
    nullable: bool = True


def predict_output_schema(
    node_type: str,
    config: dict[str, Any],
    input_schemas: dict[str, list[FieldDescriptor]],
    *,
    connection_strings: dict[str, str] | None = None,
) -> list[FieldDescriptor] | None:
    """Prediz o schema de saída de um nó sem executá-lo.

    Parâmetros
    ----------
    node_type:
        Tipo do nó (ex: "filter", "mapper", "join").
    config:
        Config bruta do nó (campos podem ter ${} não resolvidos).
    input_schemas:
        Mapa handle → schema dos upstreams. Handle "input" é o padrão
        para nós com uma entrada; "left"/"right" para join/lookup.
    connection_strings:
        Mapa connection_id → connection_string já resolvido pelo caller.
        Quando presente, sql_database probe a conexão via SELECT...LIMIT 0.
        Quando ausente ou sem entrada para a connection_id, retorna None.

    Retorna
    -------
    list[FieldDescriptor]
        Schema previsto de saída.
    None
        Schema desconhecido para este tipo (só após execução real).
    """
    handler = _HANDLERS.get(node_type)
    if handler is None:
        return None
    try:
        if node_type == "sql_database":
            return _sql_database_schema(config, input_schemas, connection_strings)
        return handler(config, input_schemas)
    except Exception:  # noqa: BLE001 — schema inference nunca quebra fluxo
        return None


# ── Handlers por node_type ─────────────────────────────────────────────────


def _filter_schema(
    config: dict[str, Any],
    input_schemas: dict[str, list[FieldDescriptor]],
) -> list[FieldDescriptor] | None:
    """Filter não altera colunas — schema de saída = schema de entrada."""
    return _primary_input(input_schemas)


def _mapper_schema(
    config: dict[str, Any],
    input_schemas: dict[str, list[FieldDescriptor]],
) -> list[FieldDescriptor] | None:
    """Mapper: saída declarada em config.mappings."""
    mappings = config.get("mappings") or []
    if not mappings:
        return None

    input_fields = {f.name: f for f in (_primary_input(input_schemas) or [])}
    result: list[FieldDescriptor] = []

    for m in mappings:
        target = m.get("target")
        if not target or "${" in str(target):
            return None  # unresolved placeholder

        source = m.get("source")
        declared_type = m.get("type")

        if declared_type:
            dtype = _normalize_sql_type(str(declared_type))
        elif source and source in input_fields:
            dtype = input_fields[source].data_type
        else:
            dtype = "VARCHAR"

        result.append(FieldDescriptor(name=target, data_type=dtype, nullable=True))

    return result or None


def _join_schema(
    config: dict[str, Any],
    input_schemas: dict[str, list[FieldDescriptor]],
) -> list[FieldDescriptor] | None:
    """Join: merge de left + right com prefixo para evitar conflito."""
    # Requer handle "left" explícito ou "input" (single-input fallback).
    # Se só "right" estiver presente sem "left"/"input", não há como inferir.
    left = input_schemas.get("left") or input_schemas.get("input")
    right = input_schemas.get("right")

    if not left:
        return None

    # Chaves de join da direita que não precisam de cópia (evita duplicata).
    conditions = config.get("conditions") or []
    right_join_keys: set[str] = {
        str(c.get("right_column", ""))
        for c in conditions
        if c.get("right_column")
    }

    # Conjunto de nomes existentes para detectar colisão.
    taken: set[str] = {f.name for f in left}
    result: list[FieldDescriptor] = list(left)

    # Colunas explicitamente selecionadas.
    explicit_cols = config.get("columns") or []
    if explicit_cols:
        return _resolve_explicit_columns(explicit_cols, left, right or [], taken)

    if right:
        for f in right:
            if f.name in right_join_keys:
                continue  # chave de join da direita: skip
            name = f.name if f.name not in taken else f"right_{f.name}"
            taken.add(name)
            result.append(FieldDescriptor(name=name, data_type=f.data_type, nullable=True))

    return result or None


def _select_schema(
    config: dict[str, Any],
    input_schemas: dict[str, list[FieldDescriptor]],
) -> list[FieldDescriptor] | None:
    """Select: subset declarado em config.columns."""
    columns = config.get("columns") or config.get("output_columns") or []
    if not columns:
        return None

    input_fields = {f.name: f for f in (_primary_input(input_schemas) or [])}
    result: list[FieldDescriptor] = []

    for col in columns:
        col_name = col if isinstance(col, str) else col.get("name", "")
        if not col_name or "${" in col_name:
            return None
        fd = input_fields.get(col_name)
        if fd:
            result.append(fd)
        else:
            result.append(FieldDescriptor(name=col_name, data_type="VARCHAR", nullable=True))

    return result or None


# ── Helpers ───────────────────────────────────────────────────────────────


def _primary_input(
    input_schemas: dict[str, list[FieldDescriptor]],
) -> list[FieldDescriptor] | None:
    """Retorna o schema do handle 'input' ou o primeiro disponível."""
    if "input" in input_schemas:
        return input_schemas["input"] or None
    for schema in input_schemas.values():
        if schema:
            return schema
    return None


def _resolve_explicit_columns(
    explicit_cols: list[Any],
    left: list[FieldDescriptor],
    right: list[FieldDescriptor],
    taken: set[str],
) -> list[FieldDescriptor] | None:
    all_fields = {f.name: f for f in left + right}
    result: list[FieldDescriptor] = []
    for col in explicit_cols:
        if isinstance(col, str):
            expr, alias = col, None
        elif isinstance(col, dict):
            expr = col.get("expression", "")
            alias = col.get("alias")
        else:
            continue
        name = alias or expr.split(".")[-1].strip()
        fd = all_fields.get(name)
        if fd:
            result.append(fd)
        else:
            result.append(FieldDescriptor(name=name, data_type="VARCHAR", nullable=True))
    return result or None


_TYPE_MAP: dict[str, str] = {
    "string":   "VARCHAR",
    "str":      "VARCHAR",
    "text":     "VARCHAR",
    "integer":  "INTEGER",
    "int":      "INTEGER",
    "bigint":   "BIGINT",
    "float":    "DOUBLE",
    "double":   "DOUBLE",
    "number":   "DOUBLE",
    "boolean":  "BOOLEAN",
    "bool":     "BOOLEAN",
    "date":     "DATE",
    "datetime": "TIMESTAMP",
    "timestamp": "TIMESTAMP",
}


def _normalize_sql_type(raw: str) -> str:
    return _TYPE_MAP.get(raw.lower(), raw.upper())


# ── sql_database (probe via SELECT * FROM (...) LIMIT 0) ──────────────────


def _sql_database_schema(
    config: dict[str, Any],
    input_schemas: dict[str, list[FieldDescriptor]],
    connection_strings: dict[str, str] | None,
) -> list[FieldDescriptor] | None:
    """Probe schema de sql_database por LIMIT 0.

    Requer connection_strings pré-resolvido (caller faz a parte async via
    connection_service). Cacheia por (connection_id, sha256(query)) em
    LRU de 256 entradas.

    Retorna None graciosamente em qualquer falha — schema inference jamais
    derruba fluxo.
    """
    if not connection_strings:
        return None

    connection_id = config.get("connection_id")
    query = config.get("query")
    if not connection_id or not query:
        return None
    if "${" in str(query):
        return None  # placeholder não resolvido

    conn_str = connection_strings.get(str(connection_id))
    if not conn_str:
        return None

    key = (str(connection_id), hashlib.sha256(str(query).encode()).hexdigest())
    cached = _SQL_SCHEMA_CACHE.get(key)
    if cached is not None:
        _SQL_SCHEMA_CACHE.move_to_end(key)  # LRU touch
        return cached

    schema = _probe_sql_schema(conn_str, str(query))
    if schema is None:
        return None

    _SQL_SCHEMA_CACHE[key] = schema
    _SQL_SCHEMA_CACHE.move_to_end(key)
    while len(_SQL_SCHEMA_CACHE) > _SQL_SCHEMA_CACHE_MAX:
        _SQL_SCHEMA_CACHE.popitem(last=False)
    return schema


def _probe_sql_schema(conn_str: str, query: str) -> list[FieldDescriptor] | None:
    """Abre engine SQLAlchemy efêmera e lê cursor.description de um probe."""
    try:
        from sqlalchemy import create_engine, text  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None

    try:
        engine = create_engine(conn_str)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text(f"SELECT * FROM ({query}) AS __schema_probe LIMIT 0")
                )
                # SQLAlchemy 2.x: cursor info em result.cursor.description.
                cursor = getattr(result, "cursor", None)
                description = getattr(cursor, "description", None) if cursor else None
                keys = list(result.keys())

                fields: list[FieldDescriptor] = []
                for i, name in enumerate(keys):
                    type_code = None
                    if description and i < len(description):
                        type_code = description[i][1]
                    dtype = _map_dbapi_type(type_code)
                    fields.append(
                        FieldDescriptor(name=str(name), data_type=dtype, nullable=True)
                    )
                return fields or None
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001
        return None


def _map_dbapi_type(type_code: Any) -> str:
    """Mapeia type_code do DB-API para SQL type — best effort.

    DB-API type_code é heterogêneo (int em sqlite, classe em psycopg2).
    Quando não reconhecido, fallback para VARCHAR.
    """
    if type_code is None:
        return "VARCHAR"
    name = getattr(type_code, "__name__", None) or str(type_code)
    return _normalize_sql_type(name)


# ── Registry ──────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "filter":       _filter_schema,
    "mapper":       _mapper_schema,
    "join":         _join_schema,
    "lookup":       _join_schema,   # lookup tem mesma estrutura de left/right
    "select":       _select_schema,
    "sql_database": _sql_database_schema,
    # aggregator, pivot, code, etc.: None
}
