"""
Processador do no IF com row-partition via DuckDB.

Avalia um conjunto de condicoes sobre CADA linha da tabela DuckDB upstream
e divide o dataset em duas particoes:

- ``true``:  linhas que satisfazem a expressao (``logic`` = ``and``/``or``);
- ``false``: linhas que nao satisfazem.

Cada particao e materializada em uma tabela DuckDB propria
(``{node_id}_true`` e ``{node_id}_false``) dentro do mesmo arquivo
``.duckdb`` da entrada. O runner usa ``active_handles`` para desativar
arestas de ramos vazios e ``branches`` para rotear cada aresta de saida
para a particao correta com base no ``sourceHandle`` da aresta
(``"true"`` ou ``"false"``).

Semantica row-partition — superset do all-or-nothing
----------------------------------------------------
Com all-or-nothing (``ifElse`` classico) apenas UM ramo executa — o outro
e inteiramente ignorado. Com row-partition, AMBOS podem executar em paralelo,
cada um recebendo apenas o seu subconjunto de linhas. Um ramo so e
desativado quando sua particao fica vazia (0 linhas).

Configuracao esperada
---------------------
    conditions   : list[ { "field": "<col>", "operator": "<op>", "value": <v> } ]
    logic        : "and" | "or" (padrao "and")
    output_field : ignorado; as referencias por ramo sao retornadas em
                   ``branches["true"]`` e ``branches["false"]``.

Operadores suportados (cobre test_service legacy + filter_node)::
    eq, ne / neq, gt, gte, lt, lte, contains, startswith, endswith,
    is_null, is_not_null, like, ilike, in, not_in
"""

from __future__ import annotations

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_output_reference,
    build_table_ref,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("if_node")
class IfNodeProcessor(BaseNodeProcessor):
    """Particiona linhas upstream em ``true``/``false`` via SQL DuckDB."""

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
