"""
Processador do no de ordenacao (sort).

Ordena o dataset upstream por uma ou mais colunas, com direcao (ASC/DESC)
e posicao de nulos configuravel por coluna. Um limite opcional restringe
a saida aos N primeiros registros apos a ordenacao.
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


@register_processor("sort")
class SortNodeProcessor(BaseNodeProcessor):
    """Ordena o dataset upstream com ORDER BY e materializa em DuckDB."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        sort_columns = resolved.get("sort_columns") or []
        limit = resolved.get("limit")
        output_field = str(resolved.get("output_field", "data"))

        if not sort_columns:
            raise NodeProcessingError(
                f"No sort '{node_id}': informe ao menos uma coluna em 'sort_columns'."
            )

        order_parts = []
        for sc in sort_columns:
            col = (sc.get("column") or "").strip() if isinstance(sc, dict) else str(sc)
            if not col:
                raise NodeProcessingError(
                    f"No sort '{node_id}': cada entrada em 'sort_columns' precisa de 'column'."
                )
            direction = str(sc.get("direction", "asc") if isinstance(sc, dict) else "asc").upper()
            if direction not in {"ASC", "DESC"}:
                direction = "ASC"
            # Default: ASC → NULLS LAST, DESC → NULLS FIRST
            default_nulls = "LAST" if direction == "ASC" else "FIRST"
            if isinstance(sc, dict) and sc.get("nulls_position"):
                pos = str(sc["nulls_position"]).upper()
                nulls = pos if pos in {"FIRST", "LAST"} else default_nulls
            else:
                nulls = default_nulls
            order_parts.append(f"{quote_identifier(col)} {direction} NULLS {nulls}")

        order_clause = ", ".join(order_parts)

        limit_sql = ""
        if limit is not None:
            try:
                n = int(limit)
                if n > 0:
                    limit_sql = f"LIMIT {n}"
            except (TypeError, ValueError):
                raise NodeProcessingError(
                    f"No sort '{node_id}': 'limit' deve ser um inteiro positivo."
                )

        input_ref = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_ref)

        output_table = sanitize_name(build_next_table_name(node_id, "sorted"))
        output_ref_sql = f"main.{quote_identifier(output_table)}"

        conn = duckdb.connect(str(input_ref["database_path"]))
        try:
            row_in: int = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref}"
            ).fetchone()[0]  # type: ignore[index]
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref_sql} AS
                SELECT * FROM {source_ref}
                ORDER BY {order_clause}
                {limit_sql}
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
                "warnings": [],
            },
        }
