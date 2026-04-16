"""
Processador do no SWITCH com row-partition via DuckDB e gate mode para
upstream de metadata/status.

Dois modos de operacao, detectados automaticamente pelo shape do upstream:

1. row-partition (modo original)
   Ativado quando ao menos um upstream expoe uma referencia DuckDB real.
   Avalia o valor de ``switch_field`` em cada linha e distribui entre N
   particoes nomeadas (cases), mais uma particao ``default`` para linhas
   que nao correspondem a nenhum case.

2. gate mode (all-or-nothing)
   Ativado quando o upstream primario e um dict de metadata/status e
   nenhum upstream tem ref DuckDB. O no avalia ``switch_field`` no
   proprio dict e ativa EXATAMENTE UM handle — o label do case que
   casou, ou ``default``. Em gate mode, ``branches`` faz passthrough do
   upstream (nao cria tabelas).

Configuracao esperada
---------------------
    switch_field : nome da coluna/chave avaliada (obrigatorio).
    cases        : list[ { "label": "<handle>", "values": ["<v1>", ...] } ]

Matching e por igualdade de strings apos TRIM/CAST — coerente entre os
dois modos.
"""

from __future__ import annotations

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_output_reference,
    build_table_ref,
    find_duckdb_reference,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


_DEFAULT_HANDLE = "default"


@register_processor("switch_node")
class SwitchNodeProcessor(BaseNodeProcessor):
    """Particiona linhas em N ramos via SQL, ou opera em gate mode quando
    upstream e metadata."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        switch_field = str(resolved_config.get("switch_field") or "").strip()
        raw_cases = resolved_config.get("cases") or []

        if not isinstance(raw_cases, list):
            raise NodeProcessingError(
                f"No switch_node '{node_id}': 'cases' deve ser uma lista."
            )

        # Normaliza cases: descarta entradas sem label.
        cases: list[dict[str, Any]] = []
        for case in raw_cases:
            if not isinstance(case, dict):
                continue
            label = str(case.get("label") or "").strip()
            if not label:
                continue
            values = case.get("values") or []
            if not isinstance(values, list):
                raise NodeProcessingError(
                    f"No switch_node '{node_id}': 'values' do case '{label}' "
                    "deve ser uma lista."
                )
            cases.append({"label": label, "values": [str(v).strip() for v in values]})

        # Detecta gate mode: upstream sem ref DuckDB (so metadata/dict).
        upstream_results = context.get("upstream_results", {}) or {}
        primary_upstream = _find_primary_upstream_dict(upstream_results)
        has_tabular = _any_has_duckdb_ref(upstream_results)

        if not has_tabular and isinstance(primary_upstream, dict):
            return _process_gate_mode(
                node_id, switch_field, cases, primary_upstream
            )

        return _process_row_partition(
            node_id, switch_field, cases, context
        )


# ─── Gate mode ────────────────────────────────────────────────────────────────

def _process_gate_mode(
    node_id: str,
    switch_field: str,
    cases: list[dict[str, Any]],
    primary_upstream: dict[str, Any],
) -> dict[str, Any]:
    """Avalia ``switch_field`` no dict upstream e ativa um unico handle."""
    branches: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}

    # Todos os labels + default sempre presentes em ``branches`` para que
    # o runner consiga rotear qualquer aresta declarada. Counts zerados
    # refletem "este handle nao foi ativado".
    for case in cases:
        branches[case["label"]] = primary_upstream
        counts[case["label"]] = 0
    branches[_DEFAULT_HANDLE] = primary_upstream
    counts[_DEFAULT_HANDLE] = 0

    if not switch_field or not cases:
        matched_label = _DEFAULT_HANDLE
    else:
        raw_value = primary_upstream.get(switch_field)
        field_str = "" if raw_value is None else str(raw_value).strip()

        matched_label = _DEFAULT_HANDLE
        if raw_value is not None:
            for case in cases:
                if field_str in case["values"]:
                    matched_label = case["label"]
                    break

    counts[matched_label] = 1

    result: dict[str, Any] = {
        "node_id": node_id,
        "status": "completed",
        "branches": branches,
        "active_handles": [matched_label],
        "row_count": 1,
        "gate_mode": True,
    }
    for handle, count in counts.items():
        result[f"{handle}_count"] = count
    return result


def _find_primary_upstream_dict(
    upstream_results: dict[str, Any],
) -> dict[str, Any] | None:
    """Retorna o upstream mais recente que seja um dict."""
    if not isinstance(upstream_results, dict):
        return None
    for value in reversed(list(upstream_results.values())):
        if isinstance(value, dict):
            return value
    return None


def _any_has_duckdb_ref(upstream_results: dict[str, Any]) -> bool:
    """Indica se algum upstream carrega uma referencia DuckDB."""
    if not isinstance(upstream_results, dict):
        return False
    for value in upstream_results.values():
        if find_duckdb_reference(value) is not None:
            return True
    return False


# ─── Row-partition (modo original) ────────────────────────────────────────────

def _process_row_partition(
    node_id: str,
    switch_field: str,
    cases: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Particiona linhas do DuckDB upstream por case."""
    input_reference = get_primary_input_reference(context, node_id)
    source_ref = build_table_ref(input_reference)

    # Tabela por case + default
    branches: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}

    conn = duckdb.connect(str(input_reference["database_path"]))
    try:
        if not switch_field or not cases:
            # Sem config util: tudo vai para "default", demais handles ficam vazios.
            default_table = sanitize_name(f"{node_id}_{_DEFAULT_HANDLE}")
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE main.{quote_identifier(default_table)} AS
                SELECT * FROM {source_ref}
                """
            )
            default_ref = build_output_reference(input_reference, default_table)
            default_count = _count_rows(conn, default_table)

            branches[_DEFAULT_HANDLE] = default_ref
            counts[_DEFAULT_HANDLE] = default_count

            # Cria tabelas vazias para cada case declarado (para rotas
            # existentes nao quebrarem find_duckdb_reference).
            for case in cases:
                table = sanitize_name(f"{node_id}_{case['label']}")
                conn.execute(
                    f"""
                    CREATE OR REPLACE TABLE main.{quote_identifier(table)} AS
                    SELECT * FROM {source_ref} WHERE FALSE
                    """
                )
                branches[case["label"]] = build_output_reference(
                    input_reference, table
                )
                counts[case["label"]] = 0
        else:
            field_col = quote_identifier(switch_field)
            # Expressao reutilizada: valor trimado da coluna como texto
            field_expr = f"TRIM(CAST({field_col} AS VARCHAR))"

            # Valores ja atribuidos a algum case — linhas cujo valor esta
            # em algum case NAO devem cair no default.
            all_assigned_values: list[str] = []

            for case in cases:
                label = case["label"]
                values = case["values"]
                table = sanitize_name(f"{node_id}_{label}")

                if values:
                    literals = ", ".join(_sql_literal(v) for v in values)
                    where = f"{field_expr} IN ({literals})"
                    all_assigned_values.extend(values)
                else:
                    where = "FALSE"  # case sem valores — bucket sempre vazio

                conn.execute(
                    f"""
                    CREATE OR REPLACE TABLE main.{quote_identifier(table)} AS
                    SELECT * FROM {source_ref}
                    WHERE {where}
                    """
                )
                branches[label] = build_output_reference(input_reference, table)
                counts[label] = _count_rows(conn, table)

            # Default: linhas cujo valor NAO esta em nenhum case (inclui NULL).
            default_table = sanitize_name(f"{node_id}_{_DEFAULT_HANDLE}")
            if all_assigned_values:
                literals = ", ".join(_sql_literal(v) for v in all_assigned_values)
                default_where = (
                    f"{field_expr} NOT IN ({literals}) OR {field_col} IS NULL"
                )
            else:
                default_where = "TRUE"

            conn.execute(
                f"""
                CREATE OR REPLACE TABLE main.{quote_identifier(default_table)} AS
                SELECT * FROM {source_ref}
                WHERE {default_where}
                """
            )
            branches[_DEFAULT_HANDLE] = build_output_reference(
                input_reference, default_table
            )
            counts[_DEFAULT_HANDLE] = _count_rows(conn, default_table)
    finally:
        conn.close()

    active_handles = [handle for handle, count in counts.items() if count > 0]

    result: dict[str, Any] = {
        "node_id": node_id,
        "status": "completed",
        "branches": branches,
        "active_handles": active_handles,
        "row_count": sum(counts.values()),
    }
    for handle, count in counts.items():
        result[f"{handle}_count"] = count
    return result


def _sql_literal(value: Any) -> str:
    """Converte um valor Python para literal SQL seguro."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _count_rows(conn: "duckdb.DuckDBPyConnection", table_name: str) -> int:
    """Conta linhas de uma tabela DuckDB recem-criada."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM main.{quote_identifier(table_name)}"
    ).fetchone()
    return int(row[0]) if row else 0
