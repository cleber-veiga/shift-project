"""
Processador do no SWITCH com row-partition via DuckDB.

Avalia o valor de um campo em cada linha da tabela DuckDB upstream e
distribui as linhas entre N particoes nomeadas (cases), mais uma
particao ``default`` para linhas que nao correspondem a nenhum case.

Cada particao e materializada em uma tabela DuckDB propria no mesmo
arquivo ``.duckdb`` da entrada. O runner usa ``active_handles`` para
desativar arestas de ramos vazios e ``branches`` para rotear cada aresta
de saida para a particao correta com base no ``sourceHandle`` da aresta
(o label do case, ou ``"default"``).

Configuracao esperada
---------------------
    switch_field : nome da coluna avaliada em cada linha (obrigatorio).
    cases        : list[ { "label": "<handle>", "values": ["<v1>", "<v2>", ...] } ]
                   Cada case define um bucket nomeado e a lista de valores
                   que pertencem a ele. O ``sourceHandle`` no React Flow deve
                   coincidir com ``label``. Linhas que nao casam vao para
                   ``default``.

Matching e por igualdade exata entre o valor da coluna (convertido para
string e trim) e os valores declarados no case.
"""

from __future__ import annotations

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_output_reference,
    build_table_ref,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


_DEFAULT_HANDLE = "default"


@register_processor("switch_node")
class SwitchNodeProcessor(BaseNodeProcessor):
    """Particiona linhas upstream em N ramos nomeados via SQL DuckDB."""

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
