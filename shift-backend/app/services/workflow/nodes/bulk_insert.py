"""
Processador do no de bulk insert com column mapping.

Le o dataset DuckDB upstream, aplica um mapeamento de colunas
(source -> target), remove duplicatas por ``unique_columns`` e escreve
no destino SQL via ``load_service.insert`` — que faz introspeccao
automatica dos tipos da tabela destino e cast inteligente.

Leitura em chunks
-----------------
O DuckDB e lido em batches de ``batch_size`` linhas via ``fetchmany``,
nunca materializando a tabela inteira em RAM. Cada chunk e mapeado e
inserido independentemente no destino. As partitions de sucesso/erro
para branches downstream sao escritas incrementalmente em JSONL
(``JsonlStreamer``) e so materializadas em DuckDB ao final.

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
    load_strategy    : Estrategia de carga. Tres opcoes:

        ``"append_fast"`` (padrao)
            Usa dlt com commit por chunk. Alta throughput, mas em caso de
            falha parcial os chunks ja comitados ficam persistidos — nao ha
            rollback automatico. Ideal para tabelas de log ou situacoes onde
            reprocessamento parcial e aceitavel.

        ``"append_safe"``
            Usa SQLAlchemy em transacao unica. Se qualquer linha falhar, toda
            a operacao e revertida (rollback total). Garante atomicidade, mas
            requer que a conexao suporte transacoes longas. Indicado quando a
            tabela de destino nao pode ficar em estado parcial.

        ``"upsert"``
            Usa INSERT ... ON CONFLICT (PostgreSQL), INSERT ... ON DUPLICATE
            KEY UPDATE (MySQL) ou MERGE INTO (MSSQL/Oracle/Firebird). Requer
            que ``unique_columns`` esteja configurado — esses campos formam a
            chave de idempotencia. Em caso de falha o comportamento e igual ao
            ``append_safe``: transacao unica com rollback total. Use quando o
            mesmo dado pode chegar mais de uma vez e a tabela destino deve
            refletir sempre o valor mais recente.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterator

import duckdb

from app.data_pipelines.duckdb_storage import (
    JsonlStreamer,
    build_table_ref,
    get_primary_input_reference,
)
from app.services.load_service import LoadResult, RejectedRow, load_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.parameter_value import (
    ResolutionContext,
    compile_parameter,
    execute_compiled,
    parse_parameter_value,
)


_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


# ─── ParameterValue helpers ───────────────────────────────────────────────────

def _extract_pv_column_refs(pv: Any) -> list[str]:
    """Extrai colunas DuckDB referenciadas num ParameterValue dynamic."""
    if not (isinstance(pv, dict) and pv.get("mode") == "dynamic"):
        return []
    tokens = re.findall(r"\{\{([^}]+)\}\}", str(pv.get("template", "")))
    return [t.strip() for t in tokens if not t.strip().startswith(("vars.", "$"))]


def _normalize_bulk_map(m: Any) -> dict[str, Any] | None:
    """Normaliza uma entrada de column_mapping para formato interno.

    Retorna ``{'pv': PV_ou_None, 'source': str_ou_None, 'target': str}``.
    """
    if not isinstance(m, dict):
        return None
    target = str(m.get("target") or "").strip()
    if not target:
        return None
    # Novo formato: { value: ParameterValue, target }
    if "value" in m and isinstance(m.get("value"), dict) and "mode" in m["value"]:
        return {"pv": m["value"], "source": None, "target": target}
    # Legado: { source, target }
    source = str(m.get("source") or "").strip()
    if not source:
        return None
    return {"pv": None, "source": source, "target": target}


def _compile_pv_maps(
    valid_maps: list[dict[str, Any]],
) -> list[tuple[str, Any, str | None]]:
    """Pre-compila mapeamentos PV uma vez — reutilizavel por chunk."""
    compiled: list[tuple[str, Any, str | None]] = []
    for m in valid_maps:
        if m["pv"] is not None:
            compiled.append(
                (m["target"], compile_parameter(parse_parameter_value(m["pv"])), None)
            )
        else:
            compiled.append((m["target"], None, m["source"]))
    return compiled


def _apply_pv_maps(
    raw_chunk: list[dict[str, Any]],
    compiled_maps: list[tuple[str, Any, str | None]],
    ctx: ResolutionContext,
) -> list[dict[str, Any]]:
    """Aplica mapeamentos pre-compilados a um chunk de linhas."""
    resolved: list[dict[str, Any]] = []
    for row in raw_chunk:
        row_ctx = ResolutionContext(
            input_data={**ctx.input_data, **row},
            upstream_results=ctx.upstream_results,
            vars=ctx.vars,
            all_results=ctx.all_results,
        )
        resolved_row: dict[str, Any] = {}
        for target, compiled, source in compiled_maps:
            if compiled is not None:
                resolved_row[target] = execute_compiled(compiled, row_ctx)
            else:
                resolved_row[target] = row.get(source)  # type: ignore[arg-type]
        resolved.append(resolved_row)
    return resolved


def _sample_ram_mb() -> float | None:
    """Retorna uso atual de RAM do processo em MB, ou None se psutil indisponivel."""
    try:
        import psutil  # noqa: PLC0415
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        return None


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
        # Lê column_mapping do config bruto para preservar templates de ParameterValue
        raw_mapping = config.get("column_mapping") or []
        unique_columns_raw = resolved_config.get("unique_columns") or []
        batch_size = int(resolved_config.get("batch_size") or 1000)
        output_field = str(resolved_config.get("output_field", "load_result"))
        load_strategy = str(resolved_config.get("load_strategy") or "append_fast")

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
            n for m in raw_mapping if (n := _normalize_bulk_map(m)) is not None
        ]
        if not valid_maps:
            raise NodeProcessingError(
                f"No bulk_insert '{node_id}': nenhum mapeamento de colunas valido."
            )

        unique_columns: list[str] = [
            str(c) for c in unique_columns_raw if isinstance(c, str) and c.strip()
        ]

        has_pv = any(m["pv"] is not None for m in valid_maps)
        ctx = ResolutionContext(
            input_data=context.get("input_data") or {},
            upstream_results=context.get("upstream_results") or {},
            vars=context.get("vars") or {},
            all_results=context.get("_all_results") or {},
        )

        input_reference = get_primary_input_reference(context, node_id)

        # Determina colunas a ler do DuckDB e pre-compila mapeamentos
        if has_pv:
            seen: set[str] = set()
            needed_cols: list[str] = []
            for m in valid_maps:
                refs = _extract_pv_column_refs(m["pv"]) if m["pv"] else (
                    [m["source"]] if m["source"] else []
                )
                for col in refs:
                    if col not in seen:
                        seen.add(col)
                        needed_cols.append(col)
            compiled_maps = _compile_pv_maps(valid_maps)
            load_column_mapping: list[dict[str, str]] = [
                {"source": m["target"], "target": m["target"]} for m in valid_maps
            ]
        else:
            needed_cols = list({m["source"] for m in valid_maps if m["source"]})
            compiled_maps = None
            load_column_mapping = [
                {"source": m["source"], "target": m["target"]} for m in valid_maps
            ]

        execution_id_str = str(
            context.get("execution_id") or context.get("workflow_id") or node_id
        )

        # ── Metricas ──────────────────────────────────────────────────────────
        t_start = time.monotonic()
        ram_start_mb = _sample_ram_mb()
        peak_ram_delta_mb: float | None = None

        chunks_processed = 0
        has_any_data = False
        row_offset = 0

        # Acumuladores por chunk
        total_rows_received = 0
        total_rows_written = 0
        total_duplicates_removed = 0
        total_rejected: list[RejectedRow] = []
        total_successful_rn: list[int] = []
        total_failed_rn: list[int] = []
        combined_status = "success"
        dest_count_before = -1
        dest_count_after = -1
        cast_summary: dict[str, int] = {}
        column_types: dict[str, str] = {}
        columns_mapped = 0
        cast_warnings: list[str] = []
        loader = "sqlalchemy"
        duplicate_sample: list[dict[str, Any]] = []

        # Partitions de branch escritas incrementalmente em JSONL → DuckDB
        with (
            JsonlStreamer(execution_id_str, f"{node_id}_success") as success_stream,
            JsonlStreamer(execution_id_str, f"{node_id}_on_error") as error_stream,
        ):
            for raw_chunk in _read_cols_from_duckdb_chunked(
                input_reference, needed_cols, batch_size
            ):
                if not raw_chunk:
                    continue

                has_any_data = True

                # Aplica mapeamento de colunas
                if has_pv and compiled_maps is not None:
                    chunk_rows = _apply_pv_maps(raw_chunk, compiled_maps, ctx)
                else:
                    chunk_rows = raw_chunk

                if not chunk_rows:
                    row_offset += len(raw_chunk)
                    continue

                chunk_result = load_service.insert(
                    str(connection_string),
                    conn_type,
                    target_table,
                    chunk_rows,
                    column_mapping=load_column_mapping,
                    batch_size=batch_size,
                    unique_columns=unique_columns if unique_columns else None,
                    load_strategy=load_strategy,
                )
                chunks_processed += 1

                # Agrega metricas
                total_rows_received += chunk_result.rows_received
                total_rows_written += chunk_result.rows_written
                total_duplicates_removed += chunk_result.duplicates_removed

                if chunk_result.status not in ("success", "skipped"):
                    combined_status = "error"

                if chunks_processed == 1:
                    dest_count_before = chunk_result.dest_count_before
                    cast_summary = dict(chunk_result.cast_summary)
                    column_types = dict(chunk_result.column_types)
                    columns_mapped = chunk_result.columns_mapped
                    cast_warnings = list(chunk_result.cast_warnings)
                    loader = chunk_result.loader

                if chunk_result.dest_count_after >= 0:
                    dest_count_after = chunk_result.dest_count_after

                if chunk_result.duplicate_sample and len(duplicate_sample) < 5:
                    duplicate_sample.extend(
                        chunk_result.duplicate_sample[: 5 - len(duplicate_sample)]
                    )

                # Ajusta numeros de linha para offset global
                rejected_by_chunk_row = {
                    rr.row_number: rr for rr in chunk_result.rejected_rows
                }
                success_set = set(chunk_result.successful_row_numbers)

                for rr in chunk_result.rejected_rows:
                    total_rejected.append(
                        RejectedRow(
                            row_number=rr.row_number + row_offset,
                            error=rr.error,
                            column=rr.column,
                            value=rr.value,
                            expected_type=rr.expected_type,
                            failed_alias=rr.failed_alias,
                        )
                    )
                for rn in chunk_result.successful_row_numbers:
                    total_successful_rn.append(rn + row_offset)
                for rn in chunk_result.failed_row_numbers:
                    total_failed_rn.append(rn + row_offset)

                # Escrita incremental das partitions de branch em JSONL
                for row_number, row in enumerate(chunk_rows, start=1):
                    if row_number in success_set:
                        success_stream.write_row(dict(row))
                    elif row_number in rejected_by_chunk_row:
                        enriched = _enrich_failed_row(
                            dict(row), rejected_by_chunk_row[row_number]
                        )
                        error_stream.write_row(enriched)

                row_offset += len(chunk_rows)

                # Pico de RAM por chunk
                current_ram = _sample_ram_mb()
                if current_ram is not None and ram_start_mb is not None:
                    delta = current_ram - ram_start_mb
                    if peak_ram_delta_mb is None or delta > peak_ram_delta_mb:
                        peak_ram_delta_mb = delta

            # ── JsonlStreamer.__exit__ materializa os DuckDB aqui ─────────────
            success_ref = success_stream.reference
            error_ref = error_stream.reference
            success_count = success_stream.row_count
            error_count = error_stream.row_count

        if not has_any_data:
            skipped_payload = {
                "status": "skipped",
                "message": "Sem dados upstream para inserir.",
                "rows_written": 0,
                "target_table": target_table,
            }
            return {
                "node_id": node_id,
                **skipped_payload,
                "output_field": output_field,
                output_field: skipped_payload,
            }

        elapsed = time.monotonic() - t_start

        # Constroi LoadResult agregado
        aggregated = LoadResult(
            status=combined_status,
            rows_received=total_rows_received,
            rows_written=total_rows_written,
            duplicates_removed=total_duplicates_removed,
            target_table=target_table,
            dest_count_before=dest_count_before,
            dest_count_after=dest_count_after,
            cast_summary=cast_summary,
            column_types=column_types,
            columns_mapped=columns_mapped,
            cast_warnings=cast_warnings,
            loader=loader,
            batches=chunks_processed,
            rejected_rows=total_rejected,
            successful_row_numbers=total_successful_rn,
            failed_row_numbers=total_failed_rn,
            unique_columns=unique_columns,
            duplicate_sample=duplicate_sample,
        )

        result_dict = aggregated.to_dict()
        result_dict["message"] = _build_insert_report(aggregated, target_table)

        # Metricas de execucao
        result_dict["chunks_processed"] = chunks_processed
        result_dict["rows_per_second"] = (
            round(total_rows_written / elapsed) if elapsed > 0 else 0
        )
        if peak_ram_delta_mb is not None:
            result_dict["peak_ram_mb"] = round(peak_ram_delta_mb, 1)

        _attach_branch_outputs_from_streams(
            result_dict=result_dict,
            success_reference=success_ref,
            error_reference=error_ref,
            success_count=success_count,
            error_count=error_count,
            total_rejected=total_rejected,
            node_id=node_id,
        )

        return {
            "node_id": node_id,
            **result_dict,
            "output_field": output_field,
            output_field: result_dict,
        }


def _read_cols_from_duckdb_chunked(
    reference: dict[str, Any],
    columns: list[str],
    chunk_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Projeta colunas da tabela DuckDB upstream em batches via fetchmany.

    Nunca carrega a tabela inteira em RAM — cada yield e um batch de
    no maximo ``chunk_size`` linhas.
    """
    if not columns:
        return

    table_ref = build_table_ref(reference)
    projection = ", ".join(_quote_identifier(c) for c in columns)

    conn = duckdb.connect(str(reference["database_path"]), read_only=True)
    try:
        cursor = conn.execute(f"SELECT {projection} FROM {table_ref}")
        col_names = [desc[0] for desc in cursor.description]
        while True:
            batch = cursor.fetchmany(chunk_size)
            if not batch:
                break
            yield [dict(zip(col_names, row)) for row in batch]
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


def _attach_branch_outputs_from_streams(
    *,
    result_dict: dict[str, Any],
    success_reference: Any,
    error_reference: Any,
    success_count: int,
    error_count: int,
    total_rejected: list[RejectedRow],
    node_id: str,
) -> None:
    """Conecta as referencias DuckDB das partitions de branch ao resultado."""
    branches: dict[str, Any] = {}
    active_handles: list[str] = []

    if success_reference is not None:
        branches["success"] = success_reference
        active_handles.append("success")
        result_dict["succeeded_rows_count"] = success_count

    if error_reference is not None:
        branches["on_error"] = error_reference
        active_handles.append("on_error")
        result_dict["failed_rows_count"] = error_count
        result_dict["failed_node"] = node_id
        if total_rejected:
            result_dict["error"] = total_rejected[0].error

    if branches:
        result_dict["branches"] = branches
        result_dict["active_handles"] = active_handles


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
