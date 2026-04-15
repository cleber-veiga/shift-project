"""
Processadores de nos de condicao (if/else e switch).

Avaliam condicoes sobre datasets DuckDB e retornam a referencia de entrada
intacta (pass-through) junto com o handle ativo, permitindo que o orquestrador
ative apenas o ramo correto do grafo.

O campo ``active_handle`` no resultado e lido pelo dynamic_runner para
determinar quais arestas de saida estao ativas e quais devem ser ignoradas.
"""

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_table_ref,
    get_primary_input_reference,
    quote_identifier,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


# Mapa de operadores suportados — identico ao do filter_node para consistencia.
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


@register_processor("ifElse")
class IfElseNodeProcessor(BaseNodeProcessor):
    """
    Avalia uma condicao sobre o dataset upstream e ativa o handle 'true' ou 'false'.

    O dataset e passado adiante intacto (pass-through). O orquestrador le o
    campo ``active_handle`` do resultado para rotear a execucao ao ramo correto
    e ignorar o ramo inativo junto com todos os seus descendentes.

    Configuracao esperada::

        {
            "conditions": [
                {"field": "status", "operator": "eq", "value": "ativo"}
            ],
            "logic": "and"   // "and" | "or", padrao: "and"
        }

    Handles de saida esperados nas arestas do React Flow: ``"true"`` e ``"false"``.
    """

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
                f"No ifElse '{node_id}': logic deve ser 'and' ou 'or'."
            )
        if not conditions:
            raise NodeProcessingError(
                f"No ifElse '{node_id}': informe ao menos uma condicao."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        clauses = [_build_condition_clause(cond, node_id) for cond in conditions]
        where_clause = f" {logic} ".join(clauses)

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref} WHERE {where_clause}"
            ).fetchone()
        finally:
            conn.close()

        count = row[0] if row else 0
        active_handle = "true" if count > 0 else "false"

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: input_reference,  # pass-through — o dado nao e transformado
            "active_handle": active_handle,
        }


@register_processor("switch")
class SwitchNodeProcessor(BaseNodeProcessor):
    """
    Avalia uma lista ordenada de cases e ativa o handle do primeiro verdadeiro.

    Se nenhum case for satisfeito, ativa o ``default_handle``. O dataset e
    passado adiante intacto (pass-through). O orquestrador le ``active_handle``
    para rotear o fluxo ao ramo correto.

    Configuracao esperada::

        {
            "cases": [
                {
                    "handle_id": "alto_valor",
                    "conditions": [{"field": "valor", "operator": "gte", "value": 1000}],
                    "logic": "and"
                },
                {
                    "handle_id": "medio_valor",
                    "conditions": [{"field": "valor", "operator": "gte", "value": 100}],
                    "logic": "and"
                }
            ],
            "default_handle": "baixo_valor"
        }

    O ``handle_id`` de cada case deve corresponder ao ``sourceHandle`` da aresta
    no React Flow. O ``default_handle`` e ativado quando nenhum case corresponde.
    """

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        cases = resolved_config.get("cases") or []
        default_handle = str(resolved_config.get("default_handle", "default"))
        output_field = str(resolved_config.get("output_field", "data"))

        if not cases:
            raise NodeProcessingError(
                f"No switch '{node_id}': informe ao menos um case."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            active_handle = _evaluate_switch_cases(
                conn, source_ref, cases, default_handle, node_id
            )
        finally:
            conn.close()

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: input_reference,  # pass-through — o dado nao e transformado
            "active_handle": active_handle,
        }


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _evaluate_switch_cases(
    conn: "duckdb.DuckDBPyConnection",
    source_ref: str,
    cases: list[dict[str, Any]],
    default_handle: str,
    node_id: str,
) -> str:
    """Avalia os cases do switch em ordem e retorna o handle ativo."""
    for case in cases:
        handle_id = str(case.get("handle_id", "")).strip()
        conditions = case.get("conditions") or []
        logic = str(case.get("logic", "and")).upper()

        if not handle_id:
            raise NodeProcessingError(
                f"No switch '{node_id}': cada case precisa de 'handle_id'."
            )
        if not conditions:
            raise NodeProcessingError(
                f"No switch '{node_id}': case '{handle_id}' precisa de ao menos uma condicao."
            )
        if logic not in {"AND", "OR"}:
            raise NodeProcessingError(
                f"No switch '{node_id}': logic do case '{handle_id}' deve ser 'and' ou 'or'."
            )

        clauses = [_build_condition_clause(cond, node_id) for cond in conditions]
        where_clause = f" {logic} ".join(clauses)

        row = conn.execute(
            f"SELECT COUNT(*) FROM {source_ref} WHERE {where_clause}"
        ).fetchone()
        count = row[0] if row else 0

        if count > 0:
            return handle_id

    return default_handle


def _build_condition_clause(condition: dict[str, Any], node_id: str) -> str:
    """Converte uma condicao em uma clausula SQL DuckDB."""
    field = condition.get("field")
    operator = str(condition.get("operator", "eq")).lower()
    value = condition.get("value")

    if not field:
        raise NodeProcessingError(
            f"No condicao '{node_id}': cada condicao precisa de 'field'."
        )

    col = quote_identifier(str(field))

    if operator == "is_null":
        return f"{col} IS NULL"

    if operator == "is_not_null":
        return f"{col} IS NOT NULL"

    if operator == "in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No condicao '{node_id}': operador 'in' requer uma lista em 'value'."
            )
        literals = ", ".join(_sql_literal(v) for v in value)
        return f"{col} IN ({literals})"

    if operator == "not_in":
        if not isinstance(value, list):
            raise NodeProcessingError(
                f"No condicao '{node_id}': operador 'not_in' requer uma lista em 'value'."
            )
        literals = ", ".join(_sql_literal(v) for v in value)
        return f"{col} NOT IN ({literals})"

    if operator == "contains":
        escaped = str(value).replace("'", "''")
        return f"{col} LIKE '%{escaped}%'"

    sql_op = _SQL_OPERATORS.get(operator)
    if sql_op is None:
        raise NodeProcessingError(
            f"No condicao '{node_id}': operador '{operator}' nao suportado."
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
