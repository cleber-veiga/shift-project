"""
Processador do no composto personalizavel.

Um "no personalizado" na paleta do workflow e um snapshot de
``CustomNodeDefinition`` carregado em ``node.data.blueprint``. Este
processador le o blueprint + field_mapping da config e orquestra
insercoes em cascata (multiplas tabelas relacionadas) dentro de uma
unica transacao no banco de destino.

Configuracao do no
------------------
    connection_id   : UUID do conector SQL de destino (resolvido pelo runner
                      para ``connection_string``).
    blueprint       : Contrato ``{"tables": [...]}``. Cada item contem
                      alias, table, role (header|child), parent_alias,
                      fk_map, columns, returning e cardinality.
    field_mapping   : Mapa ``{"alias.coluna": "coluna_upstream"}`` ligando
                      colunas das tabelas alvo aos campos da linha upstream.
    output_field    : Chave do payload de saida (padrao ``"composite_result"``).

Cardinalidade
-------------
Phase 1 aceita apenas ``cardinality == "one"`` por tabela — cada linha
upstream vira uma linha em cada tabela. Multi-row children (1 NOTA -> N
NOTAITEM) fica para Phase 2 (requer modelo de unnest ou agrupamento).
"""

from __future__ import annotations

import re
from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_table_ref,
    ensure_duckdb_reference,
    get_primary_input_reference,
)
from app.services.load_service import RejectedRow, load_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.parameter_value import (
    ResolutionContext,
    compile_parameter,
    execute_compiled,
    parse_parameter_value,
    resolve_parameter,
)


@register_processor("composite_insert")
class CompositeInsertProcessor(BaseNodeProcessor):
    """Insere linhas do DuckDB upstream em multiplas tabelas relacionadas."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)

        connection_string = resolved_config.get("connection_string")
        blueprint = resolved_config.get("blueprint")
        # Lê field_mapping do config bruto para preservar templates de ParameterValue
        field_mapping = config.get("field_mapping") or {}
        output_field = str(resolved_config.get("output_field", "composite_result"))

        if not connection_string:
            raise NodeProcessingError(
                f"No composite_insert '{node_id}': connection_string e obrigatorio."
            )
        if not isinstance(blueprint, dict) or not blueprint.get("tables"):
            raise NodeProcessingError(
                f"No composite_insert '{node_id}': blueprint.tables e obrigatorio."
            )
        if not isinstance(field_mapping, dict):
            raise NodeProcessingError(
                f"No composite_insert '{node_id}': field_mapping deve ser dict."
            )

        conn_type = _infer_conn_type(str(connection_string))
        if conn_type in {"firebird", "mysql"}:
            raise NodeProcessingError(
                f"No composite_insert '{node_id}': {conn_type} nao suportado no Phase 1."
            )

        upstream_columns = _collect_upstream_columns(field_mapping)
        if not upstream_columns:
            raise NodeProcessingError(
                f"No composite_insert '{node_id}': field_mapping vazio — "
                "nao ha colunas upstream para ler."
            )

        ctx = ResolutionContext(
            input_data=context.get("input_data") or {},
            upstream_results=context.get("upstream_results") or {},
            vars=context.get("vars") or {},
        )

        input_reference = get_primary_input_reference(context, node_id)
        raw_rows = _read_rows_from_duckdb(input_reference, upstream_columns)
        rows, string_mapping = _resolve_composite_rows(raw_rows, field_mapping, ctx)

        if not rows:
            skipped_payload = {
                "status": "skipped",
                "message": "Sem dados upstream para inserir.",
                "rows_written": 0,
                "rows_received": 0,
                "steps": [],
            }
            return {
                "node_id": node_id,
                **skipped_payload,
                "output_field": output_field,
                output_field: skipped_payload,
            }

        try:
            result = load_service.insert_composite(
                str(connection_string),
                conn_type,
                blueprint,
                string_mapping,
                rows,
            )
        except ValueError as exc:
            # Blueprint malformado ou dialeto nao suportado — falha funcional.
            raise NodeProcessingError(
                f"No composite_insert '{node_id}': {exc}"
            ) from exc

        result_dict = result.to_dict()
        result_dict["message"] = _build_report(result)
        execution_id = str(
            context.get("execution_id") or context.get("workflow_id") or node_id
        )
        _attach_branch_outputs(
            result_dict=result_dict,
            rows=rows,
            rejected_rows=result.rejected_rows,
            successful_row_numbers=result.successful_row_numbers,
            execution_id=execution_id,
            node_id=node_id,
        )

        return {
            "node_id": node_id,
            **result_dict,
            "output_field": output_field,
            output_field: result_dict,
        }


def _collect_upstream_columns(field_mapping: dict[str, Any]) -> list[str]:
    """Extrai colunas distintas do upstream referenciadas pelo mapping.

    Aceita tanto strings (legado) quanto ParameterValue dicts (novo formato).
    """
    cols: set[str] = set()
    for key, upstream in field_mapping.items():
        if not isinstance(key, str) or "." not in key:
            continue
        if isinstance(upstream, str) and upstream.strip():
            cols.add(upstream)
        elif isinstance(upstream, dict) and upstream.get("mode") == "dynamic":
            tokens = re.findall(r"\{\{([^}]+)\}\}", str(upstream.get("template", "")))
            for t in tokens:
                t = t.strip()
                if not t.startswith(("vars.", "$")):
                    cols.add(t)
    return sorted(cols)


def _resolve_composite_rows(
    raw_rows: list[dict[str, Any]],
    field_mapping: dict[str, Any],
    ctx: ResolutionContext,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Resolve ParameterValue values em field_mapping por linha.

    Para entries PV, injeta colunas sinteticas ``__pv_N`` nas linhas e
    retorna um string_mapping equivalente para ``insert_composite``.
    """
    pv_entries: list[tuple[str, Any]] = []
    string_entries: dict[str, str] = {}

    for key, val in field_mapping.items():
        if isinstance(val, dict) and "mode" in val:
            pv_entries.append((key, val))
        elif isinstance(val, str) and val.strip():
            string_entries[key] = val

    if not pv_entries:
        return raw_rows, string_entries

    # Mapeia alias.col → nome de coluna sintetica
    pv_col: dict[str, str] = {
        key: f"__pv_{i}" for i, (key, _) in enumerate(pv_entries)
    }

    # Pre-compila cada PV uma vez fora do loop — elimina Pydantic + regex por linha.
    compiled_pv: list[tuple[str, Any]] = [
        (key, compile_parameter(parse_parameter_value(pv_raw)))
        for key, pv_raw in pv_entries
    ]

    augmented: list[dict[str, Any]] = []
    for row in raw_rows:
        row_ctx = ResolutionContext(
            input_data={**ctx.input_data, **row},
            upstream_results=ctx.upstream_results,
            vars=ctx.vars,
        )
        aug = dict(row)
        for key, compiled in compiled_pv:
            aug[pv_col[key]] = execute_compiled(compiled, row_ctx)
        augmented.append(aug)

    merged_mapping = {
        **string_entries,
        **{key: pv_col[key] for key, _ in pv_entries},
    }
    return augmented, merged_mapping


def _read_rows_from_duckdb(
    reference: dict[str, Any],
    upstream_columns: list[str],
) -> list[dict[str, Any]]:
    """Projeta apenas as colunas necessarias do DuckDB upstream."""
    if not upstream_columns:
        return []

    table_ref = build_table_ref(reference)
    projection = ", ".join(_quote_identifier(c) for c in upstream_columns)

    conn = duckdb.connect(str(reference["database_path"]), read_only=True)
    try:
        cursor = conn.execute(f"SELECT {projection} FROM {table_ref}")
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _infer_conn_type(connection_string: str) -> str:
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
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _build_report(result: Any) -> str:
    lines = [
        f"{result.rows_written}/{result.rows_received} linhas fonte processadas."
    ]
    for step in result.steps:
        lines.append(f"{step.alias} ({step.table}): {step.rows_written}")
    if result.failed_at_alias:
        lines.append(
            f"Falha em alias='{result.failed_at_alias}' "
            f"(linha #{result.failed_at_row_index}): {result.error_message}"
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
    if rejected_row.failed_alias is not None:
        row["_dead_letter_failed_alias"] = rejected_row.failed_alias
    return row
