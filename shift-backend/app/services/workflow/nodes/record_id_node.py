"""
Processador do no de ID sequencial (record_id).

Adiciona uma coluna de ID incremental ao dataset usando ROW_NUMBER() OVER().
Suporta particao (PARTITION BY) e ordenacao (ORDER BY) para controlar
a numeracao dentro de grupos e a ordem dentro de cada grupo.

Sem 'order_by', ROW_NUMBER() tem ordem nao deterministica — o processador
aceita mas nao emite warning (comportamento delegado ao frontend).
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


@register_processor("record_id")
class RecordIdNodeProcessor(BaseNodeProcessor):
    """Adiciona coluna de ID sequencial via ROW_NUMBER() OVER()."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        id_column = str(resolved.get("id_column", "id")).strip() or "id"
        start_at = resolved.get("start_at", 1)
        partition_by: list[str] = resolved.get("partition_by") or []
        order_by: list[Any] = resolved.get("order_by") or []
        output_field = str(resolved.get("output_field", "data"))

        try:
            start_at = int(start_at)
        except (TypeError, ValueError):
            raise NodeProcessingError(
                f"No record_id '{node_id}': 'start_at' deve ser um inteiro."
            )

        # PARTITION BY clause
        if partition_by:
            parts = []
            for col in partition_by:
                col_str = str(col).strip()
                if not col_str:
                    raise NodeProcessingError(
                        f"No record_id '{node_id}': entrada vazia em 'partition_by'."
                    )
                parts.append(quote_identifier(col_str))
            partition_clause = f"PARTITION BY {', '.join(parts)}"
        else:
            partition_clause = ""

        # ORDER BY clause
        if order_by:
            ob_parts = []
            for ob in order_by:
                if isinstance(ob, dict):
                    col = str(ob.get("column", "")).strip()
                    direction = str(ob.get("direction", "asc")).upper()
                    if direction not in {"ASC", "DESC"}:
                        direction = "ASC"
                else:
                    col = str(ob).strip()
                    direction = "ASC"
                if not col:
                    raise NodeProcessingError(
                        f"No record_id '{node_id}': coluna vazia em 'order_by'."
                    )
                ob_parts.append(f"{quote_identifier(col)} {direction}")
            order_clause = f"ORDER BY {', '.join(ob_parts)}"
        else:
            order_clause = ""

        over_parts = " ".join(p for p in [partition_clause, order_clause] if p)
        over_clause = f"({over_parts})"
        offset = start_at - 1
        id_col_quoted = quote_identifier(id_column)

        input_ref = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_ref)

        output_table = sanitize_name(build_next_table_name(node_id, "with_id"))
        output_ref_sql = f"main.{quote_identifier(output_table)}"

        warnings: list[str] = []
        if not order_by:
            # Sem ORDER BY, ROW_NUMBER() pode atribuir IDs em ordem distinta
            # entre runs sobre o mesmo dado — IDs viram não-reproduzíveis.
            warnings.append("non_deterministic_without_order_by")

        conn = duckdb.connect(str(input_ref["database_path"]))
        try:
            row_in: int = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref}"
            ).fetchone()[0]  # type: ignore[index]
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref_sql} AS
                SELECT ROW_NUMBER() OVER {over_clause} + {offset} AS {id_col_quoted},
                       *
                FROM {source_ref}
                """
            )
            row_out: int = conn.execute(
                f"SELECT COUNT(*) FROM {output_ref_sql}"
            ).fetchone()[0]  # type: ignore[index]
        finally:
            conn.close()

        output_reference = build_output_reference(input_ref, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
            "output_summary": {
                "row_count_in": row_in,
                "row_count_out": row_out,
                "warnings": warnings,
            },
        }
