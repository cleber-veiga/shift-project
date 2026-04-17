"""
Processador do no de bulk insert com column mapping.

Le o dataset DuckDB upstream, aplica um mapeamento de colunas
(source -> target), remove duplicatas por ``unique_columns`` e escreve
no destino SQL via ``load_service.insert`` — que faz introspeccao
automatica dos tipos da tabela destino e cast inteligente.

Configuracao do no
------------------
    connection_id    : UUID do conector SQL de destino (resolvido pelo runner
                       para ``connection_string``).
    target_table     : Nome da tabela, opcionalmente com schema.
    column_mapping   : Lista de ``{"source": "<col_origem>", "target": "<col_destino>"}``
                       descrevendo como mapear colunas do DuckDB para a tabela.
                       Obrigatorio.
    unique_columns   : Lista de colunas (em ``target``) usadas para dedup
                       interno antes do insert. Opcional.
    batch_size       : Tamanho do lote do insert (padrao 1000).
    output_field     : Nome do campo com o relatorio de carga (padrao
                       ``"load_result"``).
"""

from __future__ import annotations

import re
from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    ensure_duckdb_reference,
    build_table_ref,
    get_primary_input_reference,
)
from app.services.load_service import RejectedRow, load_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


@register_processor("bulk_insert")
class BulkInsertProcessor(BaseNodeProcessor):
    """Insere linhas do DuckDB upstream no destino com mapeamento de colunas."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)

        connection_string = resolved_config.get("connection_string")
        target_table = str(resolved_config.get("target_table") or "").strip()
        raw_mapping = resolved_config.get("column_mapping") or []
        unique_columns_raw = resolved_config.get("unique_columns") or []
        batch_size = int(resolved_config.get("batch_size") or 1000)
        output_field = str(resolved_config.get("output_field", "load_result"))

        if not connection_string:
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': connection_string e obrigatorio."
            )
        if not target_table:
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': target_table e obrigatorio."
            )
        if not _TABLE_NAME_RE.match(target_table):
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': nome de tabela invalido "
                f"'{target_table}'."
            )

        conn_type = _infer_conn_type(str(connection_string))
        if conn_type == "firebird":
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': escrita em Firebird nao suportada."
            )

        if not isinstance(raw_mapping, list) or not raw_mapping:
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': column_mapping e obrigatorio."
            )

        valid_maps = [
            {"source": str(m["source"]), "target": str(m["target"])}
            for m in raw_mapping
            if isinstance(m, dict) and m.get("source") and m.get("target")
        ]
        if not valid_maps:
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': nenhum mapeamento de colunas valido."
            )

        unique_columns: list[str] = [
            str(c) for c in unique_columns_raw if isinstance(c, str) and c.strip()
        ]

        input_reference = get_primary_input_reference(context, node_id)
        rows = _read_rows_from_duckdb(input_reference, valid_maps)

        if not rows:
            skipped_payload = {
                "status": "skipped",
                "message": "Sem dados upstream para inserir.",
                "rows_written": 0,
                "target_table": target_table,
            }
            # Top-level status reflete o resultado da operacao (parity com
            # workflow_test_service). Downstream if_node pode gate em
            # ``status == "skipped"`` ou ``!= "success"``.
            return {
                "node_id": node_id,
                **skipped_payload,
                "output_field": output_field,
                output_field: skipped_payload,
            }

        load_result = load_service.insert(
            str(connection_string),
            conn_type,
            target_table,
            rows,
            column_mapping=valid_maps,
            batch_size=batch_size,
            unique_columns=unique_columns if unique_columns else None,
        )

        result_dict = load_result.to_dict()
        result_dict["message"] = _build_insert_report(load_result, target_table)
        execution_id = str(
            context.get("execution_id") or context.get("workflow_id") or node_id
        )
        _attach_branch_outputs(
            result_dict=result_dict,
            rows=rows,
            rejected_rows=load_result.rejected_rows,
            successful_row_numbers=load_result.successful_row_numbers,
            execution_id=execution_id,
            node_id=node_id,
        )

        # Top-level status vem do LoadResult (``success``/``error``) para
        # parity com workflow_test_service e para habilitar if_node gates.
        return {
            "node_id": node_id,
            **result_dict,
            "output_field": output_field,
            output_field: result_dict,
        }


def _read_rows_from_duckdb(
    reference: dict[str, Any],
    column_mapping: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """
    Le apenas as colunas necessarias (source) da tabela DuckDB upstream.

    Retorna ``list[dict]`` com os nomes de colunas do SOURCE — o
    ``load_service.insert`` aplica o mapping source->target internamente.
    """
    source_cols = list({m["source"] for m in column_mapping})
    if not source_cols:
        return []

    table_ref = build_table_ref(reference)
    # Projeta apenas as colunas de origem para reduzir memoria
    projection = ", ".join(_quote_identifier(c) for c in source_cols)

    conn = duckdb.connect(str(reference["database_path"]), read_only=True)
    try:
        cursor = conn.execute(f"SELECT {projection} FROM {table_ref}")
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _infer_conn_type(connection_string: str) -> str:
    """Deriva o tipo do conector a partir do prefixo da URL SQLAlchemy."""
    cs = connection_string.lower()
    if cs.startswith(("postgresql", "postgres")):
        return "postgres"
    if cs.startswith(("mssql", "sqlserver")):
        return "sqlserver"
    if cs.startswith(("mysql", "mariadb")):
        return "mysql"
    if cs.startswith("oracle"):
        return "oracle"
    if cs.startswith("firebird"):
        return "firebird"
    if cs.startswith("sqlite"):
        return "sqlite"
    return ""


def _quote_identifier(identifier: str) -> str:
    """Escapa identificadores para uso seguro em SQL DuckDB."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _build_insert_report(result: Any, target_table: str) -> str:
    """Monta relatorio textual com metricas do insert."""
    lines: list[str] = [
        f"{result.rows_written} linhas gravadas em '{target_table}'."
    ]
    if result.rows_received > 0:
        lines.append(f"Recebidas: {result.rows_received}")
    if result.duplicates_removed > 0:
        lines.append(f"Duplicatas removidas: {result.duplicates_removed}")
        if result.unique_columns:
            lines.append(f"Chave de dedup: [{', '.join(result.unique_columns)}]")
    if result.rejected_rows:
        lines.append(f"Rejeitadas: {len(result.rejected_rows)}")
    if result.dest_count_before >= 0 and result.dest_count_after >= 0:
        lines.append(
            f"Destino: {result.dest_count_before} antes -> "
            f"{result.dest_count_after} depois"
        )
    return " | ".join(lines)


def _attach_branch_outputs(
    *,
    result_dict: dict[str, Any],
    rows: list[dict[str, Any]],
    rejected_rows: list[RejectedRow],
    successful_row_numbers: list[int],
    execution_id: str,
    node_id: str,
) -> None:
    rejected_by_row = {row.row_number: row for row in rejected_rows}
    success_set = set(successful_row_numbers)

    success_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        if row_number in success_set:
            success_rows.append(dict(row))
        elif row_number in rejected_by_row:
            failed_rows.append(
                _enrich_failed_row(dict(row), rejected_by_row[row_number])
            )

    branches: dict[str, Any] = {}
    active_handles: list[str] = []
    if success_rows:
        branches["success"] = ensure_duckdb_reference(
            success_rows,
            execution_id,
            f"{node_id}_success",
        )
        active_handles.append("success")
    if failed_rows:
        branches["on_error"] = ensure_duckdb_reference(
            failed_rows,
            execution_id,
            f"{node_id}_on_error",
        )
        active_handles.append("on_error")
        result_dict["failed_node"] = node_id
        result_dict["error"] = failed_rows[0].get("_dead_letter_error")

    if branches:
        result_dict["branches"] = branches
        result_dict["active_handles"] = active_handles
    if success_rows:
        result_dict["succeeded_rows_count"] = len(success_rows)
    if failed_rows:
        result_dict["failed_rows_count"] = len(failed_rows)


def _enrich_failed_row(
    row: dict[str, Any],
    rejected_row: RejectedRow,
) -> dict[str, Any]:
    row["_dead_letter_row_number"] = rejected_row.row_number
    row["_dead_letter_error"] = rejected_row.error
    if rejected_row.column is not None:
        row["_dead_letter_column"] = rejected_row.column
    if rejected_row.expected_type is not None:
        row["_dead_letter_expected_type"] = rejected_row.expected_type
    if rejected_row.value is not None:
        row["_dead_letter_value"] = rejected_row.value
    return row
