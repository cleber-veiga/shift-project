"""
Processador do no de join.

Cruza dois datasets DuckDB identificados pelas portas de entrada ``left`` e
``right``. O no exige que o React Flow conecte as arestas com ``targetHandle``
igual a ``"left"`` ou ``"right"`` para que o runner injete ``edge_handles`` no
contexto e este processador consiga distinguir os dois upstreams.

Quando os dois datasets estao em arquivos DuckDB distintos, o no realiza
ATTACH do banco direito no banco esquerdo e executa o JOIN dentro de uma
unica conexao. O resultado e sempre materializado no banco esquerdo.

Configuracao:
- join_type   : "inner" | "left" | "right" | "full"  (padrao: "inner")
- conditions  : lista de {left_column, right_column}
- columns     : lista de colunas/expressoes a selecionar (opcional).
                Cada item pode ser uma string SQL ou um dict
                {"expression": "...", "alias": "..."}.
                Se omitido, seleciona todas as colunas da esquerda e da direita
                (excluindo as chaves de join da direita para evitar duplicatas).
- output_field: nome do campo de saida (padrao: "data")
"""

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    DuckDbReference,
    build_next_table_name,
    build_output_reference,
    build_table_ref,
    get_named_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError

_VALID_JOIN_TYPES = {"inner", "left", "right", "full"}
_ATTACH_ALIAS = "__join_right_db__"


@register_processor("join")
class JoinNodeProcessor(BaseNodeProcessor):
    """Cruza dois datasets via SQL JOIN no DuckDB."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        join_type = str(resolved_config.get("join_type", "inner")).lower()
        conditions = resolved_config.get("conditions") or []
        columns = resolved_config.get("columns") or []
        output_field = str(resolved_config.get("output_field", "data"))

        if join_type not in _VALID_JOIN_TYPES:
            raise NodeProcessingError(
                f"No join '{node_id}': join_type deve ser um de {_VALID_JOIN_TYPES}."
            )
        if not conditions:
            raise NodeProcessingError(
                f"No join '{node_id}': informe ao menos uma condicao em 'conditions'."
            )

        left_ref = get_named_input_reference(context, node_id, "left")
        right_ref = get_named_input_reference(context, node_id, "right")

        conn, right_table = _open_with_right(left_ref, right_ref)
        left_table = build_table_ref(left_ref)

        # Clausula ON
        on_parts = []
        for cond in conditions:
            left_col = cond.get("left_column")
            right_col = cond.get("right_column")
            if not left_col or not right_col:
                raise NodeProcessingError(
                    f"No join '{node_id}': cada condicao requer 'left_column' e 'right_column'."
                )
            on_parts.append(
                f"l.{quote_identifier(str(left_col))} = r.{quote_identifier(str(right_col))}"
            )
        on_clause = " AND ".join(on_parts)

        # Clausula SELECT
        if columns:
            select_parts = []
            for col in columns:
                if isinstance(col, str):
                    select_parts.append(col)
                elif isinstance(col, dict):
                    expr = col.get("expression", "")
                    alias = col.get("alias")
                    if alias:
                        select_parts.append(f"({expr}) AS {quote_identifier(str(alias))}")
                    else:
                        select_parts.append(str(expr))
            select_clause = ", ".join(select_parts)
        else:
            # Padrao: tudo da esquerda + tudo da direita excluindo as chaves de join
            right_keys = {str(c["right_column"]) for c in conditions if c.get("right_column")}
            if right_keys:
                excl = ", ".join(quote_identifier(k) for k in right_keys)
                right_cols = f"r.* EXCLUDE ({excl})"
            else:
                right_cols = "r.*"
            select_clause = f"l.*, {right_cols}"

        sql_join = join_type.upper()
        if sql_join == "FULL":
            sql_join = "FULL OUTER"

        output_table = sanitize_name(build_next_table_name(node_id, "joined"))
        output_ref_sql = f"main.{quote_identifier(output_table)}"

        try:
            conn.execute(f"""
                CREATE OR REPLACE TABLE {output_ref_sql} AS
                SELECT {select_clause}
                FROM {left_table} l
                {sql_join} JOIN {right_table} r
                ON {on_clause}
            """)
        finally:
            conn.close()

        output_reference = build_output_reference(left_ref, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }


def _open_with_right(
    left_ref: DuckDbReference,
    right_ref: DuckDbReference,
) -> tuple[duckdb.DuckDBPyConnection, str]:
    """
    Abre conexao no banco esquerdo e, se o banco direito for diferente,
    realiza ATTACH para permitir o JOIN entre arquivos distintos.

    Retorna ``(conn, right_table_ref)`` onde ``right_table_ref`` e a
    referencia qualificada da tabela direita pronta para uso em SQL.
    """
    conn = duckdb.connect(str(left_ref["database_path"]))

    if str(left_ref["database_path"]) == str(right_ref["database_path"]):
        right_table_ref = build_table_ref(right_ref)
    else:
        conn.execute(
            f"ATTACH '{right_ref['database_path']}' AS {quote_identifier(_ATTACH_ALIAS)} (READ_ONLY)"
        )
        schema = right_ref.get("dataset_name") or "main"
        table = str(right_ref["table_name"])
        right_table_ref = (
            f"{quote_identifier(_ATTACH_ALIAS)}"
            f".{quote_identifier(schema)}"
            f".{quote_identifier(table)}"
        )

    return conn, right_table_ref
