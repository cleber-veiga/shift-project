"""
Processador de extracao SQL com dlt e materializacao em DuckDB temporario.

Delega para extraction_service que centraliza toda logica de leitura.
"""

from typing import Any
from uuid import uuid4

from app.services.extraction_service import extraction_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("sql_database")
@register_processor("extractNode")
class SqlDatabaseProcessor(BaseNodeProcessor):
    """Extrai dados SQL em streaming e devolve uma referencia de storage."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        connection_string = resolved_config.get("connection_string")
        table_name = resolved_config.get("table_name")
        query = resolved_config.get("query")
        output_field = str(resolved_config.get("output_field", "data"))
        chunk_size = int(resolved_config.get("chunk_size", 1000))
        max_rows = resolved_config.get("max_rows")

        if not connection_string:
            raise NodeProcessingError(
                f"No SQL '{node_id}': connection_string e obrigatorio."
            )

        if not query and not table_name:
            raise NodeProcessingError(
                f"No SQL '{node_id}': informe query ou table_name."
            )

        effective_query = str(query).strip() if query else f"SELECT * FROM {table_name}"
        lowered_query = effective_query.lstrip().lower()
        if not (lowered_query.startswith("select") or lowered_query.startswith("with")):
            raise NodeProcessingError(
                f"No SQL '{node_id}': apenas queries de extracao sao suportadas."
            )

        execution_id = str(
            context.get("execution_id")
            or context.get("workflow_id")
            or uuid4()
        )

        result = extraction_service.extract_sql_to_duckdb(
            connection_string=str(connection_string),
            query=effective_query,
            execution_id=execution_id,
            resource_name=node_id,
            table_name=str(table_name) if table_name else node_id,
            max_rows=int(max_rows) if max_rows is not None else None,
            chunk_size=chunk_size,
        )

        return {
            "node_id": node_id,
            "status": "completed",
            "query": effective_query,
            "output_field": output_field,
            output_field: result.to_dict(),
        }
