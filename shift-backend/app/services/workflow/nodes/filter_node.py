"""
Processador do no de filtro.

Filtra linhas do dataset upstream com base em condicoes SQL, materializando
o resultado em uma nova tabela DuckDB. As condicoes sao traduzidas para
SQL nativo do DuckDB, o que suporta qualquer tipo de dado e operador.

A tabela de saida e sempre criada no schema principal (main) do DuckDB,
independente do schema de origem (ex: shift_extract criado pelo dlt).
"""

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_next_table_name,
    build_output_reference,
    build_table_ref,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


# Mapa de operadores suportados para traducao SQL
_SQL_OPERATORS: dict[str, str] = {
    "eq": "=",
    "ne": "!=",
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
    "in": "IN",
    "not_in": "NOT IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
    "contains": "LIKE",
}


@register_processor("filter")
class FilterNodeProcessor(BaseNodeProcessor):
    """Filtra linhas do dataset upstream usando SQL DuckDB."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        logic = str(resolved_config.get("logic", "and")).upper()
        conditions = resolved_config.get("conditions") or []
        output_field = str(resolved_config.get("output_field", "data"))

        if logic not in {"AND", "OR"}:
            raise NodeProcessingError(
                f"No filter '{node_id}': logic deve ser 'and' ou 'or'."
            )
        if not conditions:
            raise NodeProcessingError(
                f"No filter '{node_id}': informe ao menos uma condicao."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        clauses = [_build_sql_clause(cond, node_id) for cond in conditions]
        where_clause = f" {logic} ".join(clauses)
        output_table = sanitize_name(build_next_table_name(node_id, "filtered"))

        # A tabela de saida e sempre criada no schema principal (main).
        output_ref = f"main.{quote_identifier(output_table)}"

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref} AS
                SELECT * FROM {source_ref}
                WHERE {where_clause}
                """
            )
        finally:
            conn.close()

        output_reference = build_output_reference(input_reference, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }


def _build_sql_clause(condition: dict[str, Any], node_id: str) -> str:
    """Converte uma condicao de filtro em uma clausula SQL DuckDB."""
    field = condition.get("field")
    operator = str(condition.get("operator", "eq")).lower()
    value = condition.get("value")

    if not field:
        raise NodeProcessingError(
            f"No filter '{node_id}': cada condicao precisa de 'field'."
        )

    col = quote_identifier(str(field))

    if operator == "is_null":
        return f"{col} IS NULL"

    if operator == "is_not_null":
        return f"{col} IS NOT NULL"

    if operator == "in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No filter '{node_id}': operador 'in' requer uma lista em 'value'."
            )
        literals = ", ".join(_sql_literal(v) for v in value)
        return f"{col} IN ({literals})"

    if operator == "not_in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No filter '{node_id}': operador 'not_in' requer uma lista em 'value'."
            )
        literals = ", ".join(_sql_literal(v) for v in value)
        return f"{col} NOT IN ({literals})"

    if operator == "contains":
        escaped = str(value).replace("'", "''")
        return f"{col} LIKE '%{escaped}%'"

    sql_op = _SQL_OPERATORS.get(operator)
    if sql_op is None:
        raise NodeProcessingError(
            f"No filter '{node_id}': operador '{operator}' nao suportado."
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
