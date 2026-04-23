"""
Processador do no de filtro.

Filtra linhas do dataset upstream com base em condicoes SQL, materializando
o resultado em uma nova tabela DuckDB. As condicoes sao traduzidas para
SQL nativo do DuckDB, o que suporta qualquer tipo de dado e operador.

A tabela de saida e sempre criada no schema principal (main) do DuckDB,
independente do schema de origem (ex: shift_extract criado pelo dlt).

Formatos de condicao aceitos
----------------------------
- Legado:  {"field": "COL", "operator": "eq", "value": <v>}
- Novo:    {"left": ParameterValue, "operator": "eq", "right": ParameterValue}

O lado 'left' de uma condicao nova deve resolver para o nome da coluna SQL.
O lado 'right' e resolvido via resolve_parameter e suporta {{vars.X}},
{{upstream.node.campo}}, valores fixos, etc.
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
from app.services.workflow.parameter_value import (
    ResolutionContext,
    extract_field_reference,
    parse_parameter_value,
    resolve_parameter,
)


# Mapa de operadores suportados para traducao SQL
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
    "in": "IN",
    "not_in": "NOT IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
    "contains": "LIKE",
    "startswith": "LIKE",
    "endswith": "LIKE",
}


# ─── Adaptadores de formato ───────────────────────────────────────────────────

def _resolve_right_value(right: Any, ctx: ResolutionContext) -> Any:
    """Resolve o lado direito via ParameterValue quando aplicável."""
    if isinstance(right, dict) and "mode" in right:
        pv = parse_parameter_value(right)
        return resolve_parameter(pv, ctx)
    return right


def _normalize_condition(
    cond: dict[str, Any], ctx: ResolutionContext
) -> dict[str, Any]:
    """Normaliza condição para o formato interno {field, operator, value}.

    Aceita:
    - Legado: {field, operator, value}
    - Novo:   {left: ParameterValue, operator, right: ParameterValue}
    """
    if "left" in cond or "right" in cond:
        return {
            "field": extract_field_reference(cond.get("left")),
            "operator": cond.get("operator", "eq"),
            "value": _resolve_right_value(cond.get("right"), ctx),
        }
    return cond


# ─── Processador ─────────────────────────────────────────────────────────────

@register_processor("filter")
class FilterNodeProcessor(BaseNodeProcessor):
    """Filtra linhas do dataset upstream usando SQL DuckDB."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        logic = str(self.resolve_data(config.get("logic", "and"), context)).upper()
        output_field = str(
            self.resolve_data(config.get("output_field", "data"), context)
        )
        raw_conditions = config.get("conditions") or []

        if logic not in {"AND", "OR"}:
            raise NodeProcessingError(
                f"No filter '{node_id}': logic deve ser 'and' ou 'or'."
            )
        if not raw_conditions:
            raise NodeProcessingError(
                f"No filter '{node_id}': informe ao menos uma condicao."
            )

        ctx = ResolutionContext(
            input_data=context.get("input_data") or {},
            upstream_results=context.get("upstream_results") or {},
            vars=context.get("vars") or {},
            all_results=context.get("_all_results") or {},
        )
        conditions = [_normalize_condition(c, ctx) for c in raw_conditions]

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        clauses = [_build_sql_clause(cond, node_id) for cond in conditions]
        where_clause = f" {logic} ".join(clauses)
        output_table = sanitize_name(build_next_table_name(node_id, "filtered"))
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

    if operator == "startswith":
        escaped = str(value).replace("'", "''")
        return f"{col} LIKE '{escaped}%'"

    if operator == "endswith":
        escaped = str(value).replace("'", "''")
        return f"{col} LIKE '%{escaped}'"

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
