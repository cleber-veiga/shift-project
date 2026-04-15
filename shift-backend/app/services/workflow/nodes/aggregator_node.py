"""
Processador do no de agregacao.

Agrupa linhas do dataset upstream e calcula metricas (SUM, AVG, COUNT,
MAX, MIN) usando SQL DuckDB. O resultado e materializado em uma nova
tabela DuckDB e passado adiante como referencia.

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


@register_processor("aggregator")
class AggregatorNodeProcessor(BaseNodeProcessor):
    """Agrupa dados e calcula metricas em DuckDB."""

    _OPERATION_MAP = {
        "sum": "SUM",
        "avg": "AVG",
        "count": "COUNT",
        "max": "MAX",
        "min": "MIN",
    }

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        input_reference = get_primary_input_reference(context, node_id)
        output_field = str(resolved_config.get("output_field", "data"))
        group_by = [str(item) for item in resolved_config.get("group_by", [])]
        aggregations = resolved_config.get("aggregations") or []

        if not aggregations:
            raise NodeProcessingError(
                f"No aggregator '{node_id}': informe ao menos uma agregacao."
            )

        select_items: list[str] = [
            quote_identifier(column) for column in group_by
        ]
        for aggregation in aggregations:
            operation = str(aggregation["operation"]).lower()
            sql_operation = self._OPERATION_MAP.get(operation)
            if sql_operation is None:
                raise NodeProcessingError(
                    f"No aggregator '{node_id}': operacao '{operation}' nao suportada. "
                    f"Use: {', '.join(self._OPERATION_MAP.keys())}."
                )

            column = aggregation.get("column")
            column_expr = (
                "*"
                if operation == "count" and not column
                else quote_identifier(str(column))
            )
            select_items.append(
                f"{sql_operation}({column_expr}) AS {quote_identifier(str(aggregation['alias']))}"
            )

        output_table = sanitize_name(build_next_table_name(node_id, "aggregated"))
        group_by_clause = (
            f" GROUP BY {', '.join(quote_identifier(col) for col in group_by)}"
            if group_by
            else ""
        )
        source_ref = build_table_ref(input_reference)

        # A tabela de saida e sempre criada no schema principal (main).
        output_ref = f"main.{quote_identifier(output_table)}"

        connection = duckdb.connect(str(input_reference["database_path"]))
        try:
            connection.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref} AS
                SELECT {", ".join(select_items)}
                FROM {source_ref}
                {group_by_clause}
                """
            )
        finally:
            connection.close()

        output_reference = build_output_reference(input_reference, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }
