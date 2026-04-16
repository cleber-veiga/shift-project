"""
Processador do no IF com row-partition via DuckDB e gate mode para
upstream de metadata/status.

Dois modos de operacao, detectados automaticamente pelo shape do upstream:

1. row-partition (modo original)
   Ativado quando ao menos um upstream expoe uma referencia DuckDB real
   (dados tabulares). Avalia as condicoes sobre CADA linha da tabela
   DuckDB e divide o dataset em duas particoes materializadas
   (``{node_id}_true`` e ``{node_id}_false``). Ambos os ramos podem
   executar em paralelo, cada um recebendo seu subconjunto. Um ramo so
   e desativado quando sua particao fica vazia.

2. gate mode (all-or-nothing)
   Ativado quando o upstream primario e um dict de metadata/status
   (ex: ``{"status": "success", "rows_affected": 42}``) e nenhum
   upstream tem ref DuckDB. O no avalia as condicoes contra o proprio
   dict como se fosse uma unica linha e ativa EXATAMENTE UM handle:
   ``true`` se a expressao passou, ``false`` caso contrario. Em gate
   mode, ``branches`` faz passthrough do upstream (nao cria tabelas).

Configuracao esperada
---------------------
    conditions   : list[ { "field": "<col>", "operator": "<op>", "value": <v> } ]
    logic        : "and" | "or" (padrao "and")

Operadores suportados::
    eq, ne / neq, gt, gte, lt, lte, contains, startswith, endswith,
    is_null, is_not_null, like, ilike, in, not_in
"""

from __future__ import annotations

import re
from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_output_reference,
    build_table_ref,
    find_duckdb_reference,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("if_node")
class IfNodeProcessor(BaseNodeProcessor):
    """Particiona linhas upstream em ``true``/``false`` via SQL DuckDB,
    ou opera em gate mode quando upstream e metadata."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        logic = str(resolved_config.get("logic", "and")).upper()
        conditions = resolved_config.get("conditions") or []

        if logic not in {"AND", "OR"}:
            raise NodeProcessingError(
                f"No if_node '{node_id}': logic deve ser 'and' ou 'or'."
            )

        # Detecta gate mode: upstream sem ref DuckDB (so metadata/dict).
        upstream_results = context.get("upstream_results", {}) or {}
        primary_upstream = _find_primary_upstream_dict(upstream_results)
        has_tabular = _any_has_duckdb_ref(upstream_results)

        if not has_tabular and isinstance(primary_upstream, dict):
            return _process_gate_mode(
                node_id, conditions, logic, primary_upstream
            )

        return _process_row_partition(
            node_id, conditions, logic, context
        )


# ─── Gate mode ────────────────────────────────────────────────────────────────

def _process_gate_mode(
    node_id: str,
    conditions: list[dict[str, Any]],
    logic: str,
    primary_upstream: dict[str, Any],
) -> dict[str, Any]:
    """Avalia as condicoes contra o dict upstream e ativa um unico handle."""
    if not conditions:
        passed = True
    else:
        results = [
            _evaluate_condition_py(cond, primary_upstream, node_id)
            for cond in conditions
        ]
        passed = all(results) if logic == "AND" else any(results)

    active_handle = "true" if passed else "false"

    return {
        "node_id": node_id,
        "status": "completed",
        "branches": {
            "true": primary_upstream,
            "false": primary_upstream,
        },
        "active_handles": [active_handle],
        "row_count": 1,
        "true_count": 1 if passed else 0,
        "false_count": 0 if passed else 1,
        "gate_mode": True,
    }


def _find_primary_upstream_dict(
    upstream_results: dict[str, Any],
) -> dict[str, Any] | None:
    """Retorna o upstream mais recente que seja um dict."""
    if not isinstance(upstream_results, dict):
        return None
    for value in reversed(list(upstream_results.values())):
        if isinstance(value, dict):
            return value
    return None


def _any_has_duckdb_ref(upstream_results: dict[str, Any]) -> bool:
    """Indica se algum upstream carrega uma referencia DuckDB."""
    if not isinstance(upstream_results, dict):
        return False
    for value in upstream_results.values():
        if find_duckdb_reference(value) is not None:
            return True
    return False


def _evaluate_condition_py(
    condition: dict[str, Any],
    record: dict[str, Any],
    node_id: str,
) -> bool:
    """Avalia uma unica condicao em Python puro contra um dict."""
    field = condition.get("field")
    operator = str(condition.get("operator", "eq")).lower()
    value = condition.get("value")

    if not field:
        raise NodeProcessingError(
            f"No if_node '{node_id}': cada condicao precisa de 'field'."
        )

    field_value = record.get(str(field))

    if operator == "is_null":
        return field_value is None
    if operator == "is_not_null":
        return field_value is not None

    if operator == "in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No if_node '{node_id}': operador 'in' requer lista em 'value'."
            )
        return field_value in value
    if operator == "not_in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No if_node '{node_id}': operador 'not_in' requer lista em 'value'."
            )
        return field_value not in value

    # Para os operadores abaixo, campo ausente (None) nunca satisfaz —
    # espelha a semantica SQL onde comparacao com NULL e UNKNOWN.
    if field_value is None:
        return False

    if operator in {"eq"}:
        return _loose_equal(field_value, value)
    if operator in {"ne", "neq"}:
        return not _loose_equal(field_value, value)

    if operator in {"gt", "gte", "lt", "lte"}:
        return _safe_ordering(field_value, value, operator)

    if operator == "contains":
        return str(value).lower() in str(field_value).lower()
    if operator == "startswith":
        return str(field_value).lower().startswith(str(value).lower())
    if operator == "endswith":
        return str(field_value).lower().endswith(str(value).lower())

    if operator == "like":
        return _sql_like_match(str(field_value), str(value), case_insensitive=False)
    if operator == "ilike":
        return _sql_like_match(str(field_value), str(value), case_insensitive=True)

    raise NodeProcessingError(
        f"No if_node '{node_id}': operador '{operator}' nao suportado."
    )


def _loose_equal(a: Any, b: Any) -> bool:
    """Igualdade com coercao leve entre numeros e strings numericas."""
    if a == b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    try:
        return str(a) == str(b)
    except Exception:
        return False


def _safe_ordering(a: Any, b: Any, operator: str) -> bool:
    """Comparacao ordinal tolerante a tipos."""
    try:
        if operator == "gt":
            return a > b  # type: ignore[operator]
        if operator == "gte":
            return a >= b  # type: ignore[operator]
        if operator == "lt":
            return a < b  # type: ignore[operator]
        if operator == "lte":
            return a <= b  # type: ignore[operator]
    except TypeError:
        # Tenta coercao para numero se ambos parecem numericos
        try:
            fa = float(a)  # type: ignore[arg-type]
            fb = float(b)  # type: ignore[arg-type]
            if operator == "gt":
                return fa > fb
            if operator == "gte":
                return fa >= fb
            if operator == "lt":
                return fa < fb
            if operator == "lte":
                return fa <= fb
        except (TypeError, ValueError):
            return False
    return False


def _sql_like_match(value: str, pattern: str, case_insensitive: bool) -> bool:
    """Converte padrao SQL LIKE/ILIKE em regex e aplica."""
    regex_parts: list[str] = []
    for char in pattern:
        if char == "%":
            regex_parts.append(".*")
        elif char == "_":
            regex_parts.append(".")
        else:
            regex_parts.append(re.escape(char))
    flags = re.DOTALL | (re.IGNORECASE if case_insensitive else 0)
    return re.match(f"^{''.join(regex_parts)}$", value, flags) is not None


# ─── Row-partition (modo original) ────────────────────────────────────────────

def _process_row_partition(
    node_id: str,
    conditions: list[dict[str, Any]],
    logic: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Particiona linhas do DuckDB upstream em ``true``/``false``."""
    input_reference = get_primary_input_reference(context, node_id)
    source_ref = build_table_ref(input_reference)

    # Sem condicoes: tudo vai para "true". Preserva a semantica do
    # test_service para compatibilidade com workflows existentes.
    if not conditions:
        where_clause = "TRUE"
        not_where_clause = "FALSE"
    else:
        clauses = [_build_condition_clause(cond, node_id) for cond in conditions]
        where_clause = f" {logic} ".join(clauses)
        # Negacao: NOT ( <clause> ) OR cols NULL seria semantica de "nao passou",
        # mas para consistencia com o test_service usamos estritamente o
        # complemento WHERE NOT(expr). Linhas onde a expressao e UNKNOWN
        # (NULLs em comparacoes) caem em FALSE — comportamento esperado.
        not_where_clause = f"NOT ({where_clause})"

    true_table = sanitize_name(f"{node_id}_true")
    false_table = sanitize_name(f"{node_id}_false")

    conn = duckdb.connect(str(input_reference["database_path"]))
    try:
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE main.{quote_identifier(true_table)} AS
            SELECT * FROM {source_ref}
            WHERE {where_clause}
            """
        )
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE main.{quote_identifier(false_table)} AS
            SELECT * FROM {source_ref}
            WHERE {not_where_clause}
            """
        )

        true_count = _count_rows(conn, true_table)
        false_count = _count_rows(conn, false_table)
    finally:
        conn.close()

    true_ref = build_output_reference(input_reference, true_table)
    false_ref = build_output_reference(input_reference, false_table)

    # ``active_handles`` so contem ramos nao vazios — o runner marca como
    # inativas as arestas dos ramos ausentes e propaga skip em cascata.
    active_handles: list[str] = []
    if true_count > 0:
        active_handles.append("true")
    if false_count > 0:
        active_handles.append("false")

    return {
        "node_id": node_id,
        "status": "completed",
        "branches": {
            "true": true_ref,
            "false": false_ref,
        },
        "active_handles": active_handles,
        "row_count": true_count + false_count,
        "true_count": true_count,
        "false_count": false_count,
    }


# ─── Construcao da clausula SQL ────────────────────────────────────────────────

_SQL_OPERATORS: dict[str, str] = {
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


def _build_condition_clause(condition: dict[str, Any], node_id: str) -> str:
    """Converte uma condicao em uma clausula SQL DuckDB."""
    field = condition.get("field")
    operator = str(condition.get("operator", "eq")).lower()
    value = condition.get("value")

    if not field:
        raise NodeProcessingError(
            f"No if_node '{node_id}': cada condicao precisa de 'field'."
        )

    col = quote_identifier(str(field))

    if operator == "is_null":
        return f"{col} IS NULL"
    if operator == "is_not_null":
        return f"{col} IS NOT NULL"

    if operator == "in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No if_node '{node_id}': operador 'in' requer lista em 'value'."
            )
        literals = ", ".join(_sql_literal(v) for v in value)
        return f"{col} IN ({literals})"

    if operator == "not_in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No if_node '{node_id}': operador 'not_in' requer lista em 'value'."
            )
        literals = ", ".join(_sql_literal(v) for v in value)
        return f"{col} NOT IN ({literals})"

    if operator == "contains":
        escaped = str(value).replace("'", "''")
        return f"CAST({col} AS VARCHAR) ILIKE '%{escaped}%'"

    if operator == "startswith":
        escaped = str(value).replace("'", "''")
        return f"CAST({col} AS VARCHAR) ILIKE '{escaped}%'"

    if operator == "endswith":
        escaped = str(value).replace("'", "''")
        return f"CAST({col} AS VARCHAR) ILIKE '%{escaped}'"

    sql_op = _SQL_OPERATORS.get(operator)
    if sql_op is None:
        raise NodeProcessingError(
            f"No if_node '{node_id}': operador '{operator}' nao suportado."
        )

    return f"{col} {sql_op} {_sql_literal(value)}"


def _sql_literal(value: Any) -> str:
    """Converte um valor Python para literal SQL seguro."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _count_rows(conn: "duckdb.DuckDBPyConnection", table_name: str) -> int:
    """Conta linhas de uma tabela DuckDB recem-criada."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM main.{quote_identifier(table_name)}"
    ).fetchone()
    return int(row[0]) if row else 0
