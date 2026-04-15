"""
Processador do no de deduplicacao.

Remove registros duplicados usando a funcao de janela
``ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)``.
O criterio de qual registro manter dentro de cada grupo e controlado por
``order_by`` + ``keep``:

- keep="first" + order_by="DATA" -> ORDER BY DATA ASC  -> mantém o mais antigo
- keep="last"  + order_by="DATA" -> ORDER BY DATA DESC -> mantém o mais recente

Configuracao:
- partition_by : lista de colunas que definem a chave de duplicidade (obrigatorio)
- order_by     : coluna de ordenacao dentro do grupo (opcional; sem ela qualquer
                 registro do grupo e mantido de forma deterministica)
- keep         : "first" | "last"  (padrao: "first")
- output_field : nome do campo de saida (padrao: "data")
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

_ROW_NUM_COL = "__shift_row_num__"


@register_processor("deduplication")
class DeduplicationNodeProcessor(BaseNodeProcessor):
    """Remove duplicatas usando ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        partition_by: list[str] = [
            str(c) for c in (resolved_config.get("partition_by") or [])
        ]
        order_by_raw = resolved_config.get("order_by")
        keep = str(resolved_config.get("keep", "first")).lower()
        output_field = str(resolved_config.get("output_field", "data"))

        if not partition_by:
            raise NodeProcessingError(
                f"No deduplication '{node_id}': informe ao menos uma coluna em 'partition_by'."
            )
        if keep not in {"first", "last"}:
            raise NodeProcessingError(
                f"No deduplication '{node_id}': 'keep' deve ser 'first' ou 'last'."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        partition_clause = ", ".join(quote_identifier(col) for col in partition_by)

        if order_by_raw:
            direction = "ASC" if keep == "first" else "DESC"
            order_clause = f"{quote_identifier(str(order_by_raw))} {direction}"
        else:
            # Sem coluna de ordenacao: usa constante para garantir resultado determinístico.
            order_clause = "(SELECT 0)"

        output_table = sanitize_name(build_next_table_name(node_id, "deduped"))
        output_ref = f"main.{quote_identifier(output_table)}"
        rn = quote_identifier(_ROW_NUM_COL)

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            conn.execute(f"""
                CREATE OR REPLACE TABLE {output_ref} AS
                SELECT * EXCLUDE ({rn})
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY {partition_clause}
                               ORDER BY {order_clause}
                           ) AS {rn}
                    FROM {source_ref}
                )
                WHERE {rn} = 1
            """)
        finally:
            conn.close()

        output_reference = build_output_reference(input_reference, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }
