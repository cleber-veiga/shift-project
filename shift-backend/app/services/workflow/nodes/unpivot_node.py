"""
Processador do no de unpivot (wide → long).

Transforma colunas em linhas, o inverso do pivot. Aceita selecao explicita
de colunas de valor ou selecao automatica por tipo (all_numeric, all_string).

Usa UNPIVOT nativo do DuckDB quando disponivel. Fallback via UNION ALL
gerado dinamicamente se a versao nao suportar ou se cast_value_to for
necessario e a versao nao suportar o cast inline.

Configuracao:
- index_columns       : colunas que permanecem como chave (nao sao transformadas)
- value_columns       : colunas a transformar em linhas (lista explicita)
- by_type             : "all_numeric" | "all_string" | None — selecao por tipo
                        (usado quando value_columns nao e fornecido)
- variable_column_name: nome da nova coluna de variaveis (default "variable")
- value_column_name   : nome da nova coluna de valores (default "value")
- cast_value_to       : tipo SQL para cast explicito das colunas de valor (opcional)
- output_field        : campo de saida (default "data")
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

_NUMERIC_TYPES = frozenset({
    "INTEGER", "INT", "BIGINT", "HUGEINT", "SMALLINT", "TINYINT",
    "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC",
})
_STRING_TYPES = frozenset({"VARCHAR", "TEXT", "CHAR", "STRING", "CLOB"})
_MAX_UNPIVOT_COLUMNS = 500


def _is_numeric_type(type_str: str) -> bool:
    t = type_str.upper().split("(")[0].strip()
    return t in _NUMERIC_TYPES


def _is_string_type(type_str: str) -> bool:
    t = type_str.upper().split("(")[0].strip()
    return t in _STRING_TYPES


@register_processor("unpivot")
class UnpivotNodeProcessor(BaseNodeProcessor):
    """Unpivot dinamico: transforma colunas em linhas."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        index_columns: list[str] = [str(c) for c in (resolved.get("index_columns") or [])]
        value_columns: list[str] = [str(c) for c in (resolved.get("value_columns") or [])]
        by_type: str | None = resolved.get("by_type")
        variable_column_name = str(resolved.get("variable_column_name", "variable")).strip() or "variable"
        value_column_name = str(resolved.get("value_column_name", "value")).strip() or "value"
        cast_value_to: str | None = resolved.get("cast_value_to")
        output_field = str(resolved.get("output_field", "data"))

        if not index_columns:
            raise NodeProcessingError(
                f"No unpivot '{node_id}': informe ao menos uma coluna em 'index_columns'."
            )
        if not value_columns and not by_type:
            raise NodeProcessingError(
                f"No unpivot '{node_id}': informe 'value_columns' ou 'by_type'."
            )
        if by_type and by_type not in {"all_numeric", "all_string"}:
            raise NodeProcessingError(
                f"No unpivot '{node_id}': 'by_type' deve ser 'all_numeric' ou 'all_string'."
            )

        input_ref = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_ref)

        conn = duckdb.connect(str(input_ref["database_path"]))
        try:
            row_in: int = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref}"
            ).fetchone()[0]  # type: ignore[index]

            # ── Resolver colunas de valor quando by_type e usado ───────────────
            if not value_columns and by_type:
                schema_rows = conn.execute(f"DESCRIBE {source_ref}").fetchall()
                index_set = set(index_columns)
                if by_type == "all_numeric":
                    value_columns = [
                        r[0] for r in schema_rows
                        if r[0] not in index_set and _is_numeric_type(str(r[1]))
                    ]
                else:  # all_string
                    value_columns = [
                        r[0] for r in schema_rows
                        if r[0] not in index_set and _is_string_type(str(r[1]))
                    ]

                if not value_columns:
                    raise NodeProcessingError(
                        f"No unpivot '{node_id}': nenhuma coluna do tipo "
                        f"'{by_type}' encontrada (alem das index_columns)."
                    )

            if len(value_columns) > _MAX_UNPIVOT_COLUMNS:
                raise NodeProcessingError(
                    f"No unpivot '{node_id}': {len(value_columns)} colunas excedem o "
                    f"limite de {_MAX_UNPIVOT_COLUMNS}. Filtre as colunas de valor."
                )

            output_table = sanitize_name(build_next_table_name(node_id, "unpivoted"))
            output_ref_sql = f"main.{quote_identifier(output_table)}"

            # ── Tentar UNPIVOT nativo primeiro ────────────────────────────────
            if not _try_native_unpivot(
                conn=conn,
                source_ref=source_ref,
                index_columns=index_columns,
                value_columns=value_columns,
                variable_col=variable_column_name,
                value_col=value_column_name,
                cast_to=cast_value_to,
                output_ref_sql=output_ref_sql,
            ):
                # ── Fallback: UNION ALL gerado ────────────────────────────────
                _union_all_unpivot(
                    conn=conn,
                    source_ref=source_ref,
                    index_columns=index_columns,
                    value_columns=value_columns,
                    variable_col=variable_column_name,
                    value_col=value_column_name,
                    cast_to=cast_value_to,
                    output_ref_sql=output_ref_sql,
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
            "unpivot_columns": value_columns,
            "output_summary": {
                "row_count_in": row_in,
                "row_count_out": row_out,
                "warnings": [],
            },
        }


def _try_native_unpivot(
    conn: duckdb.DuckDBPyConnection,
    source_ref: str,
    index_columns: list[str],
    value_columns: list[str],
    variable_col: str,
    value_col: str,
    cast_to: str | None,
    output_ref_sql: str,
) -> bool:
    """
    Tenta usar UNPIVOT nativo do DuckDB.
    Retorna True em caso de sucesso, False para fazer fallback.
    """
    try:
        val_cols_sql = ", ".join(quote_identifier(c) for c in value_columns)
        include_nulls = "INCLUDE NULLS"

        sql = (
            f"CREATE OR REPLACE TABLE {output_ref_sql} AS "
            f"SELECT * FROM {source_ref} "
            f"UNPIVOT {include_nulls} "
            f"({quote_identifier(value_col)} FOR {quote_identifier(variable_col)} IN ({val_cols_sql}))"
        )
        conn.execute(sql)

        # Se cast_value_to for pedido, aplicar em cima
        if cast_to:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref_sql} AS
                SELECT * EXCLUDE ({quote_identifier(value_col)}),
                       TRY_CAST({quote_identifier(value_col)} AS {cast_to}) AS {quote_identifier(value_col)}
                FROM {output_ref_sql}
                """
            )
        return True
    except Exception:
        return False


def _union_all_unpivot(
    conn: duckdb.DuckDBPyConnection,
    source_ref: str,
    index_columns: list[str],
    value_columns: list[str],
    variable_col: str,
    value_col: str,
    cast_to: str | None,
    output_ref_sql: str,
) -> None:
    """Fallback: gera UNION ALL com uma linha por coluna de valor."""
    idx_select = ", ".join(quote_identifier(c) for c in index_columns)

    parts: list[str] = []
    for vc in value_columns:
        escaped_name = vc.replace("'", "''")
        if cast_to:
            value_expr = f"TRY_CAST({quote_identifier(vc)} AS {cast_to})"
        else:
            value_expr = quote_identifier(vc)
        parts.append(
            f"SELECT {idx_select}, "
            f"'{escaped_name}' AS {quote_identifier(variable_col)}, "
            f"{value_expr} AS {quote_identifier(value_col)} "
            f"FROM {source_ref}"
        )

    union_sql = "\nUNION ALL\n".join(parts)
    conn.execute(f"CREATE OR REPLACE TABLE {output_ref_sql} AS {union_sql}")
