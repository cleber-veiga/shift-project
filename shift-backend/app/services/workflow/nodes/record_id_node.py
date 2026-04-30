"""
Processador do no de ID sequencial (record_id).

Adiciona uma coluna de ID incremental ao dataset usando ROW_NUMBER() OVER().
Suporta particao (PARTITION BY) e ordenacao (ORDER BY) para controlar
a numeracao dentro de grupos e a ordem dentro de cada grupo.

Sem 'order_by', ROW_NUMBER() tem ordem nao deterministica — o processador
aceita mas nao emite warning (comportamento delegado ao frontend).

start_at "linkado": tambem aceita um template
``{{upstream_results.<id>.data.<row>.<col>}}`` que e materializado via DuckDB
sob demanda — necessario porque ``data`` em nos storage-backed e uma ref
``{storage_type, database_path, table_name}``, nao linhas inline, e o
resolve_data padrao nao consegue percorrer o caminho ``data.<row>.<col>``.
"""

import re
from typing import Any, Optional

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


_SCALAR_LINK_RE = re.compile(
    r"^\s*\{\{\s*upstream_results\.([^.\s]+)\.data\.(\d+)\.([^.\s}]+)\s*\}\}\s*$"
)


def _parse_scalar_link(template: str) -> Optional[tuple[str, int, str]]:
    """Casa o template do "linkar valor" emitido pela UI: retorna
    (upstream_id, row_index, column) ou None se nao bater no padrao."""
    m = _SCALAR_LINK_RE.match(template)
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3)


def _resolve_scalar_link(
    upstream_id: str,
    row_index: int,
    column: str,
    context: dict[str, Any],
    node_id: str,
) -> Any:
    """Resolve um template ``{{upstream_results.<id>.data.<row>.<col>}}``,
    consultando DuckDB sob demanda quando o upstream esta materializado."""
    upstream_results = context.get("upstream_results") or {}
    upstream = upstream_results.get(upstream_id)
    if upstream is None:
        # Fallback para ancestrais nao-diretos (mesmo padrao do _resolve_path).
        upstream = (context.get("_all_results") or {}).get(upstream_id)
    if not isinstance(upstream, dict):
        raise NodeProcessingError(
            f"No record_id '{node_id}': nao encontrei o no de origem "
            f"'{upstream_id}' referenciado em 'start_at'."
        )

    output_field = str(upstream.get("output_field") or "data")
    data_ref = upstream.get(output_field)
    if data_ref is None:
        data_ref = upstream.get("data")

    # Caso 1: linhas inline (ex.: SQL com poucas linhas que nao materializa).
    if isinstance(data_ref, list):
        if 0 <= row_index < len(data_ref) and isinstance(data_ref[row_index], dict):
            return data_ref[row_index].get(column)
        raise NodeProcessingError(
            f"No record_id '{node_id}': linha {row_index} ou coluna '{column}' "
            f"nao existe no upstream '{upstream_id}'."
        )

    # Caso 2: referencia DuckDB → materializa via query.
    if isinstance(data_ref, dict) and data_ref.get("storage_type") == "duckdb":
        try:
            table_ref = build_table_ref(data_ref)
            db_path = str(data_ref["database_path"])
            conn = duckdb.connect(db_path)
            try:
                row = conn.execute(
                    f"SELECT {quote_identifier(column)} FROM {table_ref} "
                    f"LIMIT 1 OFFSET {int(row_index)}"
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except duckdb.Error as exc:
            raise NodeProcessingError(
                f"No record_id '{node_id}': falha ao buscar '{column}' "
                f"do upstream '{upstream_id}' — {exc}."
            ) from exc

    raise NodeProcessingError(
        f"No record_id '{node_id}': formato do output do upstream "
        f"'{upstream_id}' nao reconhecido (esperado lista inline ou ref DuckDB)."
    )


@register_processor("record_id")
class RecordIdNodeProcessor(BaseNodeProcessor):
    """Adiciona coluna de ID sequencial via ROW_NUMBER() OVER()."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # ``start_at`` pode ser um template "linkar valor" do tipo
        # ``{{upstream_results.<id>.data.<row>.<col>}}``. Esse caminho nao e
        # resolvido pelo resolve_data padrao quando o upstream e DuckDB
        # (``data`` e uma ref, nao uma lista). Resolvemos aqui sob demanda
        # antes de chamar resolve_data, para nao virar None silenciosamente.
        raw_start_in = config.get("start_at")
        if isinstance(raw_start_in, str):
            parsed = _parse_scalar_link(raw_start_in)
            if parsed is not None:
                upstream_id, row_index, column = parsed
                resolved_scalar = _resolve_scalar_link(
                    upstream_id, row_index, column, context, node_id,
                )
                # Substitui no config para que resolve_data trate como literal.
                config = {**config, "start_at": resolved_scalar}

        resolved = self.resolve_data(config, context)
        id_column = str(resolved.get("id_column", "id")).strip() or "id"
        raw_start = resolved.get("start_at", 1)
        raw_offset = resolved.get("start_at_offset", 0)
        partition_by: list[str] = resolved.get("partition_by") or []
        order_by: list[Any] = resolved.get("order_by") or []
        output_field = str(resolved.get("output_field", "data"))

        # ``start_at`` pode vir como int (modo fixo) ou str (template já
        # substituido por resolve_data). Tentamos ambos antes de falhar pra
        # dar uma mensagem util que inclua o que veio do template.
        try:
            base = int(str(raw_start).strip()) if isinstance(raw_start, str) else int(raw_start)
        except (TypeError, ValueError):
            raise NodeProcessingError(
                f"No record_id '{node_id}': 'start_at' deve ser um inteiro. "
                f"Valor recebido (apos resolucao do template): {raw_start!r}."
            )
        try:
            offset = int(raw_offset) if raw_offset is not None else 0
        except (TypeError, ValueError):
            raise NodeProcessingError(
                f"No record_id '{node_id}': 'start_at_offset' deve ser um inteiro."
            )
        start_at = base + offset
        if start_at < 1:
            raise NodeProcessingError(
                f"No record_id '{node_id}': 'start_at' final deve ser >= 1 "
                f"(recebido: base={base}, offset={offset})."
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
