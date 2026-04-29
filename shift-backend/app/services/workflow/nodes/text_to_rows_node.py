"""
Processador do no de explosao de texto em linhas (text_to_rows).

Divide uma coluna string por um delimitador e explode cada parte em uma linha
separada. Implementado via UNNEST(string_split(...)) do DuckDB.

Configuracao:
- column_to_split : coluna de entrada a dividir (obrigatorio)
- delimiter        : delimitador literal (default ",")
- output_column    : nome da coluna de saida (default: mesmo que column_to_split)
- keep_empty       : incluir partes vazias (default False)
- trim_values      : remover espacos das partes (default True)
- max_output_rows  : limite de linhas no resultado (opcional — util em modo preview)
- output_field     : campo de saida (default "data")

A coluna original e substituida pela coluna de saida na mesma posicao; se
output_column for diferente de column_to_split, a coluna original e removida
com EXCLUDE e a nova coluna e adicionada apos as demais.
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


@register_processor("text_to_rows")
class TextToRowsNodeProcessor(BaseNodeProcessor):
    """Explode coluna de texto em multiplas linhas via UNNEST."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        column_to_split = str(resolved.get("column_to_split", "")).strip()
        delimiter = str(resolved.get("delimiter", ","))
        output_column = str(resolved.get("output_column", "") or column_to_split).strip()
        keep_empty = bool(resolved.get("keep_empty", False))
        trim_values = bool(resolved.get("trim_values", True))
        max_output_rows = resolved.get("max_output_rows")
        output_field = str(resolved.get("output_field", "data"))

        if not column_to_split:
            raise NodeProcessingError(
                f"No text_to_rows '{node_id}': 'column_to_split' e obrigatorio."
            )
        if not output_column:
            output_column = column_to_split
        if not delimiter:
            raise NodeProcessingError(
                f"No text_to_rows '{node_id}': 'delimiter' nao pode ser vazio."
            )

        if max_output_rows is not None:
            try:
                max_output_rows = int(max_output_rows)
                if max_output_rows < 1:
                    raise ValueError
            except (TypeError, ValueError):
                raise NodeProcessingError(
                    f"No text_to_rows '{node_id}': 'max_output_rows' deve ser "
                    "um inteiro positivo."
                )

        input_ref = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_ref)

        conn = duckdb.connect(str(input_ref["database_path"]))
        try:
            # Conta linhas de entrada para o summary
            row_count_in: int = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref}"
            ).fetchone()[0]  # type: ignore[index]

            col_q = quote_identifier(column_to_split)
            out_q = quote_identifier(output_column)
            delim_escaped = delimiter.replace("'", "''")

            # Expressao de divisao
            split_expr = f"string_split({col_q}, '{delim_escaped}')"

            # Expressao de valor com trim opcional
            if trim_values:
                val_expr = f"TRIM(s.val)"
            else:
                val_expr = "s.val"

            # SELECT base: excluir coluna original, adicionar nova
            inner_sql = (
                f"SELECT t.* EXCLUDE ({col_q}), "
                f"{val_expr} AS {out_q} "
                f"FROM {source_ref} AS t, "
                f"UNNEST({split_expr}) AS s(val)"
            )

            # Filtrar vazios se keep_empty=False
            if not keep_empty:
                inner_sql = (
                    f"SELECT * FROM ({inner_sql}) "
                    f"WHERE {out_q} != ''"
                )

            # Limit opcional
            if max_output_rows is not None:
                inner_sql = (
                    f"SELECT * FROM ({inner_sql}) "
                    f"LIMIT {max_output_rows}"
                )

            output_table = sanitize_name(build_next_table_name(node_id, "exploded"))
            output_ref_sql = f"main.{quote_identifier(output_table)}"

            conn.execute(
                f"CREATE OR REPLACE TABLE {output_ref_sql} AS {inner_sql}"
            )

            # Conta linhas de saida para o summary
            row_count_out: int = conn.execute(
                f"SELECT COUNT(*) FROM {output_ref_sql}"
            ).fetchone()[0]  # type: ignore[index]
        finally:
            conn.close()

        fanout = round(row_count_out / row_count_in, 2) if row_count_in else 0

        # Mantém row_count_in/out e avg_fanout no topo (compat com clients
        # existentes), mas duplica em output_summary para uniformizar.
        warnings: list[str] = []
        if fanout > 10:
            warnings.append("high_fanout")

        output_reference = build_output_reference(input_ref, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
            "row_count_in": row_count_in,
            "row_count_out": row_count_out,
            "avg_fanout": fanout,
            "output_summary": {
                "row_count_in": row_count_in,
                "row_count_out": row_count_out,
                "warnings": warnings,
            },
        }
