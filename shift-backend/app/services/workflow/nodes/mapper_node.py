"""
Processador do no de mapeamento de colunas.

Renomeia, seleciona e/ou descarta colunas do dataset upstream,
materializando o resultado em uma nova tabela DuckDB. Suporta
mapeamentos simples (source -> target) e campos computados via
expressao SQL quando 'source' nao e informado.

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


@register_processor("mapper")
class MapperNodeProcessor(BaseNodeProcessor):
    """Renomeia e seleciona colunas do dataset upstream usando SQL DuckDB."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        mappings = resolved_config.get("mappings") or []
        drop_unmapped = bool(resolved_config.get("drop_unmapped", False))
        output_field = str(resolved_config.get("output_field", "data"))

        if not mappings:
            raise NodeProcessingError(
                f"No mapper '{node_id}': informe ao menos um mapping."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        # Monta os itens do SELECT
        # Cada mapping pode ser:
        #   {"source": "COL_A", "target": "COL_B"}  -> renomeia
        #   {"source": "COL_A", "target": "COL_A"}  -> mantém com mesmo nome
        #   {"target": "NOVA_COL", "expression": "COL_A * 2"}  -> campo computado
        select_items: list[str] = []
        for mapping in mappings:
            target = mapping.get("target")
            source = mapping.get("source")
            expression = mapping.get("expression")

            if not target:
                raise NodeProcessingError(
                    f"No mapper '{node_id}': cada mapping precisa de 'target'."
                )

            if expression:
                select_items.append(
                    f"({expression}) AS {quote_identifier(str(target))}"
                )
            elif source:
                select_items.append(
                    f"{quote_identifier(str(source))} AS {quote_identifier(str(target))}"
                )
            else:
                raise NodeProcessingError(
                    f"No mapper '{node_id}': mapping para '{target}' precisa de "
                    f"'source' ou 'expression'."
                )

        if drop_unmapped:
            select_clause = ", ".join(select_items)
        else:
            mapped_sources = {
                str(m["source"])
                for m in mappings
                if m.get("source") and not m.get("expression")
            }
            exclude_clause = (
                f"EXCLUDE ({', '.join(quote_identifier(s) for s in mapped_sources)})"
                if mapped_sources
                else ""
            )
            select_clause = f"* {exclude_clause}, {', '.join(select_items)}"

        output_table = sanitize_name(build_next_table_name(node_id, "mapped"))

        # A tabela de saida e sempre criada no schema principal (main).
        output_ref = f"main.{quote_identifier(output_table)}"

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref} AS
                SELECT {select_clause}
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
