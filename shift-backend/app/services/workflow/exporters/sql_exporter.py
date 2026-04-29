"""
Exportador SQL: workflow -> script DuckDB standalone.

O script gerado materializa cada no como TEMPORARY TABLE no DuckDB, na ordem
topologica, e termina com um SELECT final sobre os terminais. ``${var}``
e ATTACH de conexoes ficam como TODO no header — o usuario deve preencher
antes de executar (``duckdb < export.sql``).
"""

from __future__ import annotations

import json
from typing import Any

from app.services.workflow.exporters._common import (
    classify_node,
    collect_connections,
    collect_referenced_vars,
    build_graph,
    export_metadata,
    get_handle_inputs,
    quote_ident,
    render_var_placeholders,
    sanitize_sql_identifier,
    short_connection_alias,
    sql_literal,
    topological_order,
)
from app.services.workflow.exporters.errors import UnsupportedNodeError


_OPERATOR_SQL: dict[str, str] = {
    "eq": "=",
    "ne": "!=",
    "neq": "!=",
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
}

_DUCKDB_TYPES: dict[str, str] = {
    "string":   "VARCHAR",
    "integer":  "INTEGER",
    "float":    "DOUBLE",
    "boolean":  "BOOLEAN",
    "date":     "DATE",
    "datetime": "TIMESTAMP",
}

_AGG_OP_SQL: dict[str, str] = {
    "sum": "SUM",
    "avg": "AVG",
    "count": "COUNT",
    "max": "MAX",
    "min": "MIN",
}


class SQLExporter:
    """Converte ``WorkflowDefinition`` em script SQL DuckDB standalone."""

    def export(self, workflow_definition: dict[str, Any]) -> str:
        nodes = list(workflow_definition.get("nodes") or [])
        edges = list(workflow_definition.get("edges") or [])

        unsupported: list[dict[str, Any]] = []
        for node in nodes:
            status, reason = classify_node(node)
            if status == "unsupported":
                unsupported.append({
                    "node_id": str(node.get("id") or ""),
                    "node_type": str(node.get("type") or ""),
                    "reason": reason or "nao suportado",
                })
        if unsupported:
            raise UnsupportedNodeError(unsupported)

        adjacency, reverse_adj, in_degree, node_map, target_handle_map = build_graph(nodes, edges)
        order = topological_order(in_degree, adjacency)

        # Identifica tabelas terminais para o SELECT final. loadNode nao
        # produz uma TEMP TABLE — o exportador apenas anota o destino, e
        # o "resultado a gravar" e o upstream imediato. Por isso terminal =
        # no nao-loadNode cujas saidas vao todas para loadNode (ou nao tem
        # saida).
        terminals: list[str] = []
        for node_id in order:
            ntype = str(node_map[node_id].get("type") or "")
            if ntype == "loadNode":
                continue
            downstream = adjacency.get(node_id) or []
            data_downstream = [
                d for d in downstream
                if str(node_map[d].get("type") or "") != "loadNode"
            ]
            if not data_downstream:
                terminals.append(node_id)

        meta = export_metadata(workflow_definition)
        var_refs = collect_referenced_vars(workflow_definition)
        conn_refs = collect_connections(workflow_definition)

        parts: list[str] = []
        parts.append(_render_header(meta, var_refs, conn_refs, node_map))

        for node_id in order:
            node = node_map[node_id]
            ntype = str(node.get("type") or "")
            handler = _HANDLERS.get(ntype)
            if handler is None:
                # classify_node ja deveria ter pegado, mas defensivo:
                raise UnsupportedNodeError([{
                    "node_id": node_id,
                    "node_type": ntype,
                    "reason": "sem handler SQL registrado",
                }])

            inputs = get_handle_inputs(node_id, reverse_adj, target_handle_map)
            block = handler(node_id, node, inputs, node_map)
            parts.append(block)

        parts.append(_render_final_selects(terminals))
        return "\n\n".join(p.rstrip() for p in parts if p) + "\n"


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _render_header(
    meta: dict[str, Any],
    var_refs: dict[str, list[str]],
    conn_refs: dict[str, list[str]],
    node_map: dict[str, dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("-- " + "─" * 70)
    lines.append(f"-- Workflow: {meta.get('workflow_name') or '(unnamed)'}")
    if meta.get("workflow_id"):
        lines.append(f"-- Workflow ID: {meta['workflow_id']}")
    lines.append(f"-- Exported at: {meta['exported_at']}")
    lines.append(f"-- Generator: Shift v{meta['shift_version']} (SQL exporter)")
    lines.append("-- " + "─" * 70)
    lines.append("--")
    lines.append("-- Run with:")
    lines.append("--   duckdb < this_file.sql")
    lines.append("--")

    if var_refs:
        lines.append("-- Variables — replace ${PLACEHOLDER} before running:")
        for name in sorted(var_refs):
            users = ", ".join(var_refs[name])
            lines.append(f"--   ${{{name}}}   used in: {users}")
        lines.append("--")

    if conn_refs:
        lines.append("-- Connections — configure ATTACH before running:")
        for cid in sorted(conn_refs):
            alias = short_connection_alias(cid)
            users = ", ".join(conn_refs[cid])
            ntypes = sorted({
                str(node_map[uid].get("type") or "")
                for uid in conn_refs[cid] if uid in node_map
            })
            lines.append(f"--   {alias}   id={cid}  used in: {users}  types: {','.join(ntypes)}")
        lines.append("--")
        lines.append("-- Suggested ATTACH (replace credentials & TYPE):")
        for cid in sorted(conn_refs):
            alias = short_connection_alias(cid)
            lines.append(
                f"--   ATTACH 'postgres://USER:PASS@HOST:PORT/DB' AS {alias} "
                f"(TYPE POSTGRES, READ_ONLY);"
            )
        lines.append("--")

    lines.append("-- " + "─" * 70)
    return "\n".join(lines)


def _render_final_selects(terminals: list[str]) -> str:
    if not terminals:
        return "-- No terminal output node detected."
    out_lines = [
        "-- " + "─" * 70,
        "-- Final outputs",
        "-- " + "─" * 70,
    ]
    for t in terminals:
        ident = quote_ident(sanitize_sql_identifier(t))
        out_lines.append(f"SELECT * FROM {ident};")
    return "\n".join(out_lines)


# ---------------------------------------------------------------------------
# Helpers de bloco
# ---------------------------------------------------------------------------

def _begin_block(node_id: str, node_type: str) -> tuple[str, str]:
    """Cabecalho de comentario + nome de tabela citada para o nó."""
    table_name = sanitize_sql_identifier(node_id)
    table_ref = quote_ident(table_name)
    header = f"-- ── Node: {node_id} ({node_type}) ── \nCREATE OR REPLACE TEMPORARY TABLE {table_ref} AS"
    return header, table_ref


def _upstream_ref(handle_name: str, inputs: dict[str, str], node_id: str, node_type: str) -> str:
    upstream = inputs.get(handle_name)
    if not upstream:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": node_type,
            "reason": f"no '{node_type}' espera entrada no handle '{handle_name}' mas nao foi conectada",
        }])
    return quote_ident(sanitize_sql_identifier(upstream))


def _primary_upstream_ref(inputs: dict[str, str], node_id: str, node_type: str) -> str:
    if not inputs:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": node_type,
            "reason": f"no '{node_type}' precisa de uma entrada upstream",
        }])
    # Prefere "default", senao usa o primeiro upstream.
    for key in ("default", "input", "in"):
        if key in inputs:
            return quote_ident(sanitize_sql_identifier(inputs[key]))
    first = next(iter(inputs.values()))
    return quote_ident(sanitize_sql_identifier(first))


# ---------------------------------------------------------------------------
# Handlers — entradas
# ---------------------------------------------------------------------------

def _handle_sql_database(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    query = cfg.get("query")
    table_name = cfg.get("table_name")
    cid = cfg.get("connection_id")
    alias = short_connection_alias(str(cid)) if cid else "conn_unknown"

    header, _ref = _begin_block(node_id, "sql_database")
    lines = [header]
    if query:
        rendered_query = render_var_placeholders(str(query)).strip().rstrip(";")
        lines.append(
            f"-- TODO: ensure ATTACH alias '{alias}' refers to the same database "
            f"(see header)."
        )
        lines.append(rendered_query + ";")
    elif table_name:
        rendered_table = render_var_placeholders(str(table_name))
        lines.append(
            f"-- TODO: replace '{alias}.main.{rendered_table}' with the actual "
            f"qualified table name in your ATTACHed database."
        )
        lines.append(f"SELECT * FROM {alias}.main.{quote_ident(rendered_table)};")
    else:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": "sql_database",
            "reason": "nem 'query' nem 'table_name' informados",
        }])
    return "\n".join(lines)


def _handle_inline_data(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    raw = cfg.get("data")

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UnsupportedNodeError([{
                "node_id": node_id,
                "node_type": "inline_data",
                "reason": f"JSON invalido em 'data': {exc}",
            }]) from exc

    if isinstance(raw, dict):
        rows = [raw]
    elif isinstance(raw, list):
        rows = raw
    else:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": "inline_data",
            "reason": "'data' deve ser dict, lista de dicts ou string JSON",
        }])

    header, _ref = _begin_block(node_id, "inline_data")
    if not rows:
        return f"{header}\nSELECT NULL WHERE 1=0;"

    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise UnsupportedNodeError([{
                "node_id": node_id,
                "node_type": "inline_data",
                "reason": "cada item de 'data' deve ser um objeto {coluna: valor}",
            }])
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(str(key))

    select_parts = [f"{quote_ident(col)} AS {quote_ident(col)}" for col in columns]
    values_rows = []
    for row in rows:
        vals = [sql_literal(row.get(col)) for col in columns]
        values_rows.append(f"({', '.join(vals)})")
    column_list = ", ".join(quote_ident(c) for c in columns)
    return (
        f"{header}\n"
        f"SELECT * FROM (VALUES\n  "
        + ",\n  ".join(values_rows)
        + f"\n) AS t({column_list});"
    )


# ---------------------------------------------------------------------------
# Handlers — narrow
# ---------------------------------------------------------------------------

def _handle_filter(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    conditions = cfg.get("conditions") or []
    logic = str(cfg.get("logic") or "and").upper()
    if logic not in {"AND", "OR"}:
        logic = "AND"
    if not conditions:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": "filter",
            "reason": "filtro sem 'conditions'",
        }])

    src = _primary_upstream_ref(inputs, node_id, "filter")

    clauses = [_build_filter_clause(c, node_id) for c in conditions]
    where = f" {logic} ".join(clauses)

    header, _ref = _begin_block(node_id, "filter")
    return f"{header}\nSELECT * FROM {src}\nWHERE {where};"


def _build_filter_clause(condition: dict[str, Any], node_id: str) -> str:
    field = condition.get("field")
    if not field and isinstance(condition.get("left"), dict):
        # Formato novo {left: ParameterValue, ...}
        left = condition["left"]
        if isinstance(left, dict) and left.get("mode") == "field":
            field = left.get("value") or left.get("path")

    operator = str(condition.get("operator") or "eq").lower()
    value = condition.get("value")
    if value is None and "right" in condition:
        right = condition["right"]
        if isinstance(right, dict) and "value" in right:
            value = right["value"]

    if not field:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": "filter",
            "reason": "condicao de filtro sem 'field'",
        }])

    col = quote_ident(str(field))

    if operator == "is_null":
        return f"{col} IS NULL"
    if operator == "is_not_null":
        return f"{col} IS NOT NULL"
    if operator == "in":
        if not isinstance(value, list):
            raise UnsupportedNodeError([{
                "node_id": node_id,
                "node_type": "filter",
                "reason": "operador 'in' precisa de lista em 'value'",
            }])
        return f"{col} IN ({', '.join(sql_literal(v) for v in value)})"
    if operator == "not_in":
        if not isinstance(value, list):
            raise UnsupportedNodeError([{
                "node_id": node_id,
                "node_type": "filter",
                "reason": "operador 'not_in' precisa de lista em 'value'",
            }])
        return f"{col} NOT IN ({', '.join(sql_literal(v) for v in value)})"
    if operator == "contains":
        return f"{col} LIKE {sql_literal(f'%{value}%')}"
    if operator == "startswith":
        return f"{col} LIKE {sql_literal(f'{value}%')}"
    if operator == "endswith":
        return f"{col} LIKE {sql_literal(f'%{value}')}"

    sql_op = _OPERATOR_SQL.get(operator)
    if sql_op is None:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": "filter",
            "reason": f"operador '{operator}' nao suportado",
        }])
    return f"{col} {sql_op} {sql_literal(value)}"


def _handle_mapper(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    mappings = cfg.get("mappings") or []
    drop_unmapped = bool(cfg.get("drop_unmapped", False))
    if not mappings:
        raise UnsupportedNodeError([{
            "node_id": node_id,
            "node_type": "mapper",
            "reason": "mapper sem 'mappings'",
        }])

    src = _primary_upstream_ref(inputs, node_id, "mapper")

    select_items: list[str] = []
    mapped_sources: list[str] = []
    for mapping in mappings:
        target = mapping.get("target")
        source = mapping.get("source")
        expression = mapping.get("expression")
        ftype = mapping.get("type")

        if not target:
            raise UnsupportedNodeError([{
                "node_id": node_id,
                "node_type": "mapper",
                "reason": "mapping sem 'target'",
            }])

        if expression:
            col_expr = f"({render_var_placeholders(str(expression))})"
        elif source:
            col_expr = quote_ident(str(source))
            mapped_sources.append(str(source))
        else:
            raise UnsupportedNodeError([{
                "node_id": node_id,
                "node_type": "mapper",
                "reason": f"mapping para '{target}' precisa de 'source' ou 'expression'",
            }])

        if ftype and ftype in _DUCKDB_TYPES:
            col_expr = f"TRY_CAST({col_expr} AS {_DUCKDB_TYPES[ftype]})"

        select_items.append(f"{col_expr} AS {quote_ident(str(target))}")

    if drop_unmapped:
        select_clause = ", ".join(select_items)
    else:
        if mapped_sources:
            excl = ", ".join(quote_ident(s) for s in dict.fromkeys(mapped_sources))
            select_clause = f"* EXCLUDE ({excl}), {', '.join(select_items)}"
        else:
            select_clause = f"*, {', '.join(select_items)}"

    header, _ref = _begin_block(node_id, "mapper")
    return f"{header}\nSELECT {select_clause}\nFROM {src};"


def _handle_record_id(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    id_column = str(cfg.get("id_column") or "id").strip() or "id"
    start_at = int(cfg.get("start_at") or 1)
    partition_by = [str(c) for c in (cfg.get("partition_by") or [])]
    order_by = cfg.get("order_by") or []

    src = _primary_upstream_ref(inputs, node_id, "record_id")

    parts: list[str] = []
    if partition_by:
        parts.append("PARTITION BY " + ", ".join(quote_ident(c) for c in partition_by))
    if order_by:
        ob: list[str] = []
        for entry in order_by:
            if isinstance(entry, dict):
                col = str(entry.get("column") or "").strip()
                direction = str(entry.get("direction") or "asc").upper()
            else:
                col = str(entry).strip()
                direction = "ASC"
            if direction not in {"ASC", "DESC"}:
                direction = "ASC"
            if col:
                ob.append(f"{quote_ident(col)} {direction}")
        if ob:
            parts.append("ORDER BY " + ", ".join(ob))

    over = " ".join(parts)
    offset = start_at - 1
    over_clause = f"({over})" if over else "()"

    header, _ref = _begin_block(node_id, "record_id")
    return (
        f"{header}\n"
        f"SELECT ROW_NUMBER() OVER {over_clause} + {offset} AS {quote_ident(id_column)},\n"
        f"       *\n"
        f"FROM {src};"
    )


def _handle_sample(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    mode = str(cfg.get("mode") or "first_n").lower()
    src = _primary_upstream_ref(inputs, node_id, "sample")
    header, _ref = _begin_block(node_id, "sample")

    if mode == "first_n":
        n = cfg.get("n")
        if n is None:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "sample",
                "reason": "modo 'first_n' precisa de 'n'",
            }])
        return f"{header}\nSELECT * FROM {src} LIMIT {int(n)};"

    if mode == "random":
        n = cfg.get("n")
        if n is None:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "sample",
                "reason": "modo 'random' precisa de 'n'",
            }])
        seed = int(cfg.get("seed") or 42)
        return (
            f"{header}\n"
            f"SELECT * FROM {src} USING SAMPLE reservoir({int(n)} ROWS) "
            f"REPEATABLE({seed});"
        )

    if mode == "percent":
        pct = cfg.get("percent")
        if pct is None:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "sample",
                "reason": "modo 'percent' precisa de 'percent'",
            }])
        return f"{header}\nSELECT * FROM {src} USING SAMPLE {float(pct)} PERCENT (BERNOULLI);"

    raise UnsupportedNodeError([{
        "node_id": node_id, "node_type": "sample",
        "reason": f"modo '{mode}' invalido",
    }])


def _handle_sort(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    sort_cols = cfg.get("sort_columns") or []
    limit = cfg.get("limit")
    if not sort_cols:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "sort",
            "reason": "sort sem 'sort_columns'",
        }])

    parts: list[str] = []
    for sc in sort_cols:
        col = (sc.get("column") if isinstance(sc, dict) else str(sc) or "").strip() if sc else ""
        if not col:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "sort",
                "reason": "entrada vazia em 'sort_columns'",
            }])
        direction = str((sc.get("direction") if isinstance(sc, dict) else "asc") or "asc").upper()
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"
        default_nulls = "LAST" if direction == "ASC" else "FIRST"
        nulls_pos = (sc.get("nulls_position") if isinstance(sc, dict) else None)
        nulls = (str(nulls_pos).upper() if nulls_pos else default_nulls)
        if nulls not in {"FIRST", "LAST"}:
            nulls = default_nulls
        parts.append(f"{quote_ident(col)} {direction} NULLS {nulls}")

    src = _primary_upstream_ref(inputs, node_id, "sort")
    header, _ref = _begin_block(node_id, "sort")
    limit_sql = f"\nLIMIT {int(limit)}" if limit else ""
    return f"{header}\nSELECT * FROM {src}\nORDER BY {', '.join(parts)}{limit_sql};"


# ---------------------------------------------------------------------------
# Handlers — wide
# ---------------------------------------------------------------------------

def _handle_join(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    join_type = str(cfg.get("join_type") or "inner").lower()
    conditions = cfg.get("conditions") or []
    columns = cfg.get("columns") or []
    if not conditions:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "join",
            "reason": "join sem 'conditions'",
        }])
    if join_type not in {"inner", "left", "right", "full"}:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "join",
            "reason": f"join_type '{join_type}' invalido",
        }])

    left = _upstream_ref("left", inputs, node_id, "join")
    right = _upstream_ref("right", inputs, node_id, "join")

    on_parts: list[str] = []
    right_keys: list[str] = []
    for cond in conditions:
        lc = cond.get("left_column")
        rc = cond.get("right_column")
        if not lc or not rc:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "join",
                "reason": "cada condicao precisa de 'left_column' e 'right_column'",
            }])
        on_parts.append(f"l.{quote_ident(str(lc))} = r.{quote_ident(str(rc))}")
        right_keys.append(str(rc))
    on_clause = " AND ".join(on_parts)

    if columns:
        select_parts: list[str] = []
        for col in columns:
            if isinstance(col, str):
                select_parts.append(col)
            elif isinstance(col, dict):
                expr = col.get("expression") or ""
                alias = col.get("alias")
                if alias:
                    select_parts.append(f"({expr}) AS {quote_ident(str(alias))}")
                else:
                    select_parts.append(str(expr))
        select_clause = ", ".join(select_parts)
    else:
        if right_keys:
            excl = ", ".join(quote_ident(k) for k in dict.fromkeys(right_keys))
            select_clause = f"l.*, r.* EXCLUDE ({excl})"
        else:
            select_clause = "l.*, r.*"

    sql_join = "FULL OUTER" if join_type == "full" else join_type.upper()

    header, _ref = _begin_block(node_id, "join")
    return (
        f"{header}\n"
        f"SELECT {select_clause}\n"
        f"FROM {left} l\n"
        f"{sql_join} JOIN {right} r ON {on_clause};"
    )


def _handle_lookup(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    lookup_key = cfg.get("lookup_key")
    dictionary_key = cfg.get("dictionary_key")
    return_columns = [str(c) for c in (cfg.get("return_columns") or [])]
    if not lookup_key or not dictionary_key or not return_columns:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "lookup",
            "reason": "lookup precisa de lookup_key, dictionary_key e return_columns",
        }])

    primary = _upstream_ref("primary", inputs, node_id, "lookup")
    dictionary = _upstream_ref("dictionary", inputs, node_id, "lookup")

    enrichment = ", ".join(f"d.{quote_ident(c)}" for c in return_columns)
    on = f"p.{quote_ident(str(lookup_key))} = d.{quote_ident(str(dictionary_key))}"

    header, _ref = _begin_block(node_id, "lookup")
    return (
        f"{header}\n"
        f"SELECT p.*, {enrichment}\n"
        f"FROM {primary} p\n"
        f"LEFT JOIN {dictionary} d ON {on};"
    )


def _handle_aggregator(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    group_by = [str(c) for c in (cfg.get("group_by") or [])]
    aggregations = cfg.get("aggregations") or []
    if not aggregations:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "aggregator",
            "reason": "aggregator sem 'aggregations'",
        }])

    select_items: list[str] = [quote_ident(c) for c in group_by]
    for agg in aggregations:
        op = str(agg.get("operation") or "").lower()
        sql_op = _AGG_OP_SQL.get(op)
        if sql_op is None:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "aggregator",
                "reason": f"operacao '{op}' nao suportada",
            }])
        col = agg.get("column")
        col_expr = "*" if (op == "count" and not col) else quote_ident(str(col))
        alias = agg.get("alias")
        if not alias:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "aggregator",
                "reason": "agregacao sem 'alias'",
            }])
        select_items.append(f"{sql_op}({col_expr}) AS {quote_ident(str(alias))}")

    src = _primary_upstream_ref(inputs, node_id, "aggregator")
    group_clause = (
        f"\nGROUP BY {', '.join(quote_ident(c) for c in group_by)}"
        if group_by else ""
    )
    header, _ref = _begin_block(node_id, "aggregator")
    return f"{header}\nSELECT {', '.join(select_items)}\nFROM {src}{group_clause};"


def _handle_deduplication(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    partition_by = [str(c) for c in (cfg.get("partition_by") or [])]
    order_by_raw = cfg.get("order_by")
    keep = str(cfg.get("keep") or "first").lower()
    if not partition_by:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "deduplication",
            "reason": "deduplication sem 'partition_by'",
        }])
    if keep not in {"first", "last"}:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "deduplication",
            "reason": "'keep' deve ser 'first' ou 'last'",
        }])

    partition_clause = ", ".join(quote_ident(c) for c in partition_by)
    if order_by_raw:
        direction = "ASC" if keep == "first" else "DESC"
        order_clause = f"{quote_ident(str(order_by_raw))} {direction}"
    else:
        order_clause = "(SELECT 0)"

    src = _primary_upstream_ref(inputs, node_id, "deduplication")
    rn = quote_ident("__shift_row_num__")

    header, _ref = _begin_block(node_id, "deduplication")
    return (
        f"{header}\n"
        f"SELECT * EXCLUDE ({rn})\n"
        f"FROM (\n"
        f"  SELECT *,\n"
        f"         ROW_NUMBER() OVER (PARTITION BY {partition_clause} "
        f"ORDER BY {order_clause}) AS {rn}\n"
        f"  FROM {src}\n"
        f")\n"
        f"WHERE {rn} = 1;"
    )


def _handle_union(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    mode = str(cfg.get("mode") or "by_name").lower()
    add_source = bool(cfg.get("add_source_col", False))
    source_col = str(cfg.get("source_col_name") or "_source")

    if mode not in {"by_name", "by_position"}:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "union",
            "reason": f"mode '{mode}' invalido",
        }])

    # Identifica handles input_1, input_2, ... em ordem numerica.
    input_handles = sorted(
        (h for h in inputs if h.startswith("input_")),
        key=lambda h: int(h.split("_", 1)[1]) if h.split("_", 1)[1].isdigit() else 0,
    )
    if len(input_handles) < 2:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "union",
            "reason": (
                "union precisa de pelo menos 2 entradas conectadas em "
                "handles input_1, input_2, ..."
            ),
        }])

    keyword = "UNION ALL BY NAME" if mode == "by_name" else "UNION ALL"

    select_parts: list[str] = []
    for handle in input_handles:
        upstream = quote_ident(sanitize_sql_identifier(inputs[handle]))
        if add_source:
            select_parts.append(
                f"SELECT {sql_literal(handle)} AS {quote_ident(source_col)}, * "
                f"FROM {upstream}"
            )
        else:
            select_parts.append(f"SELECT * FROM {upstream}")

    body = f"\n{keyword}\n".join(select_parts)
    header, _ref = _begin_block(node_id, "union")
    return f"{header}\n{body};"


def _handle_pivot(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    index_columns = [str(c) for c in (cfg.get("index_columns") or [])]
    pivot_column = str(cfg.get("pivot_column") or "").strip()
    value_column = str(cfg.get("value_column") or "").strip()
    aggregations = [str(a).lower() for a in (cfg.get("aggregations") or ["sum"])]

    if not index_columns or not pivot_column or not value_column:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "pivot",
            "reason": "pivot precisa de index_columns, pivot_column e value_column",
        }])
    for agg in aggregations:
        if agg not in _AGG_OP_SQL:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "pivot",
                "reason": f"agregacao '{agg}' invalida",
            }])

    src = _primary_upstream_ref(inputs, node_id, "pivot")
    header, _ref = _begin_block(node_id, "pivot")

    # PIVOT do DuckDB descobre os valores em runtime — gera nomes de coluna
    # como ``<valor>_<agg>`` automaticamente. Como nao temos os valores no
    # build-time, delega ao DuckDB.
    using_clauses = []
    for agg in aggregations:
        sql_op = _AGG_OP_SQL[agg]
        using_clauses.append(f"{sql_op}({quote_ident(value_column)}) AS {agg}")
    using_clause = ", ".join(using_clauses)

    on_clause = quote_ident(pivot_column)
    group_clause = ", ".join(quote_ident(c) for c in index_columns)

    return (
        f"{header}\n"
        f"PIVOT {src}\n"
        f"ON {on_clause}\n"
        f"USING {using_clause}\n"
        f"GROUP BY {group_clause};"
    )


def _handle_unpivot(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    index_columns = [str(c) for c in (cfg.get("index_columns") or [])]
    value_columns = [str(c) for c in (cfg.get("value_columns") or [])]
    by_type = cfg.get("by_type")
    var_col = str(cfg.get("variable_column_name") or "variable")
    val_col = str(cfg.get("value_column_name") or "value")
    cast_to = cfg.get("cast_value_to")

    if not index_columns:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "unpivot",
            "reason": "unpivot sem 'index_columns'",
        }])
    if not value_columns:
        if by_type:
            raise UnsupportedNodeError([{
                "node_id": node_id, "node_type": "unpivot",
                "reason": (
                    "exportador SQL nao suporta 'by_type' (precisa do schema "
                    "em runtime); informe 'value_columns' explicitamente"
                ),
            }])
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "unpivot",
            "reason": "unpivot sem 'value_columns'",
        }])

    src = _primary_upstream_ref(inputs, node_id, "unpivot")
    header, _ref = _begin_block(node_id, "unpivot")

    val_cols_sql = ", ".join(quote_ident(c) for c in value_columns)
    inner = (
        f"SELECT * FROM {src}\n"
        f"UNPIVOT INCLUDE NULLS (\n"
        f"  {quote_ident(val_col)} FOR {quote_ident(var_col)} IN ({val_cols_sql})\n"
        f")"
    )
    if cast_to:
        return (
            f"{header}\n"
            f"SELECT * EXCLUDE ({quote_ident(val_col)}),\n"
            f"       TRY_CAST({quote_ident(val_col)} AS {cast_to}) AS {quote_ident(val_col)}\n"
            f"FROM (\n  {inner}\n);"
        )
    return f"{header}\n{inner};"


def _handle_text_to_rows(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    column = str(cfg.get("column_to_split") or "").strip()
    delimiter = str(cfg.get("delimiter") or ",")
    output_column = str(cfg.get("output_column") or column).strip() or column
    keep_empty = bool(cfg.get("keep_empty", False))
    trim_values = bool(cfg.get("trim_values", True))
    max_output_rows = cfg.get("max_output_rows")

    if not column or not delimiter:
        raise UnsupportedNodeError([{
            "node_id": node_id, "node_type": "text_to_rows",
            "reason": "text_to_rows precisa de column_to_split e delimiter nao-vazios",
        }])

    src = _primary_upstream_ref(inputs, node_id, "text_to_rows")
    col_q = quote_ident(column)
    out_q = quote_ident(output_column)
    val_expr = f"TRIM(s.val)" if trim_values else "s.val"

    base = (
        f"SELECT t.* EXCLUDE ({col_q}), {val_expr} AS {out_q}\n"
        f"FROM {src} AS t,\n"
        f"     UNNEST(string_split({col_q}, {sql_literal(delimiter)})) AS s(val)"
    )
    if not keep_empty:
        base = f"SELECT * FROM (\n{base}\n) WHERE {out_q} != ''"
    if max_output_rows is not None:
        base = f"SELECT * FROM (\n{base}\n) LIMIT {int(max_output_rows)}"

    header, _ref = _begin_block(node_id, "text_to_rows")
    return f"{header}\n{base};"


# ---------------------------------------------------------------------------
# Handlers — saida (loadNode)
# ---------------------------------------------------------------------------

def _handle_load(
    node_id: str,
    node: dict[str, Any],
    inputs: dict[str, str],
    node_map: dict[str, dict[str, Any]],
) -> str:
    cfg = node.get("data") or {}
    target_table = render_var_placeholders(str(cfg.get("target_table") or "<unknown>"))
    write_mode = cfg.get("write_disposition") or "append"
    cid = cfg.get("connection_id")
    alias = short_connection_alias(str(cid)) if cid else "conn_unknown"
    upstream_id = next(iter(inputs.values()), None)
    upstream_ref = (
        quote_ident(sanitize_sql_identifier(upstream_id)) if upstream_id else "<no upstream>"
    )

    return (
        f"-- ── Node: {node_id} (loadNode) — write target ─────\n"
        f"-- TODO: write {upstream_ref} into the destination database.\n"
        f"--   target_connection: {alias} (id={cid})\n"
        f"--   target_table: {target_table}\n"
        f"--   write_disposition: {write_mode}\n"
        f"-- Example (after ATTACH '{alias}'):\n"
        f"--   INSERT INTO {alias}.main.{quote_ident(target_table)} "
        f"SELECT * FROM {upstream_ref};"
    )


# ---------------------------------------------------------------------------
# Registro de handlers
# ---------------------------------------------------------------------------

_HANDLERS = {
    "sql_database":   _handle_sql_database,
    "inline_data":    _handle_inline_data,
    "filter":         _handle_filter,
    "mapper":         _handle_mapper,
    "record_id":      _handle_record_id,
    "sample":         _handle_sample,
    "sort":           _handle_sort,
    "join":           _handle_join,
    "lookup":         _handle_lookup,
    "aggregator":     _handle_aggregator,
    "deduplication":  _handle_deduplication,
    "union":          _handle_union,
    "pivot":          _handle_pivot,
    "unpivot":        _handle_unpivot,
    "text_to_rows":   _handle_text_to_rows,
    "loadNode":       _handle_load,
}
