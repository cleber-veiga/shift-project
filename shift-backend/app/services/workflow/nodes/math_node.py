"""
Processador do no matematico.

Adiciona colunas calculadas aos dados upstream materializando o resultado
em uma nova tabela DuckDB. As expressoes sao avaliadas como SQL pelo
proprio DuckDB, o que suporta qualquer operacao aritmetica, funcoes
de data, string, etc.

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


@register_processor("math")
class MathNodeProcessor(BaseNodeProcessor):
    """Adiciona colunas calculadas via expressoes SQL ao dataset upstream."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        expressions = resolved_config.get("expressions") or []
        output_field = str(resolved_config.get("output_field", "data"))

        if not expressions:
            raise NodeProcessingError(
                f"No math '{node_id}': informe ao menos uma expressao."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        extra_cols = []
        for expr in expressions:
            target = expr.get("target_column")
            expression = expr.get("expression")
            if not target or not expression:
                raise NodeProcessingError(
                    f"No math '{node_id}': cada expressao precisa de "
                    f"'target_column' e 'expression'."
                )
            extra_cols.append(
                f"({expression}) AS {quote_identifier(str(target))}"
            )

        output_table = sanitize_name(build_next_table_name(node_id, "math"))

        # A tabela de saida e sempre criada no schema principal (main).
        # O schema qualificado (ex: shift_extract) e usado apenas no FROM
        # para referenciar a tabela de origem criada pelo dlt.
        output_ref = f"main.{quote_identifier(output_table)}"

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref} AS
                SELECT *, {", ".join(extra_cols)}
                FROM {source_ref}
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
