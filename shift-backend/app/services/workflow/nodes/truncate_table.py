"""
Processador do no de truncate/delete em tabela de destino.

Limpa uma tabela SQL (TRUNCATE ou DELETE com opcional WHERE) e repassa a
referencia DuckDB upstream intacta para o proximo no — geralmente um
``bulk_insert`` que popula a tabela recem-limpa.

Configuracao do no
------------------
    connection_id   : UUID do conector SQL de destino (obrigatorio — resolvido
                      pelo runner para ``connection_string``).
    target_table    : Nome da tabela, opcionalmente com schema (ex: ``OWN.TAB``).
    mode            : ``"truncate"`` (padrao) ou ``"delete"``.
    where_clause    : WHERE opcional quando ``mode="delete"``.
    output_field    : Nome do campo de saida que encaminha os dados upstream
                      (padrao ``"data"``).
"""

from __future__ import annotations

import re
from typing import Any

from app.data_pipelines.duckdb_storage import (
    find_duckdb_reference,
    get_primary_input_reference,
)
from app.services.load_service import load_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


@register_processor("truncate_table")
class TruncateTableProcessor(BaseNodeProcessor):
    """Limpa uma tabela de destino (TRUNCATE/DELETE) e repassa dados upstream."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)

        connection_string = resolved_config.get("connection_string")
        target_table = str(resolved_config.get("target_table") or "").strip()
        mode = str(resolved_config.get("mode", "truncate")).lower()
        where_clause = str(resolved_config.get("where_clause") or "").strip()
        output_field = str(resolved_config.get("output_field", "data"))

        if not connection_string:
            raise NodeProcessingError(
                f"No truncate_table '{node_id}': connection_string e obrigatorio."
            )
        if not target_table:
            raise NodeProcessingError(
                f"No truncate_table '{node_id}': target_table e obrigatorio."
            )
        if not _TABLE_NAME_RE.match(target_table):
            raise NodeProcessingError(
                f"No truncate_table '{node_id}': nome de tabela invalido "
                f"'{target_table}'."
            )
        if mode not in {"truncate", "delete"}:
            raise NodeProcessingError(
                f"No truncate_table '{node_id}': mode deve ser 'truncate' ou 'delete'."
            )

        conn_type = _infer_conn_type(str(connection_string))
        if conn_type == "firebird":
            raise NodeProcessingError(
                f"No truncate_table '{node_id}': operacao em Firebird nao suportada."
            )

        truncate_result = load_service.truncate(
            str(connection_string),
            conn_type,
            target_table,
            mode=mode,
            where_clause=where_clause or None,
        )

        # Pass-through: repassa a referencia DuckDB upstream se existir,
        # para que um ``bulk_insert`` a jusante possa consumir.
        #
        # O top-level ``status`` reflete o resultado da operacao
        # (``"success"`` / ``"error"``) — mesmo contrato do
        # ``workflow_test_service``. Isso permite que um ``if_node``
        # downstream gate o fluxo com ``field="status" eq "success"``.
        result_dict = truncate_result.to_dict()
        output: dict[str, Any] = {
            "node_id": node_id,
            **result_dict,
            "output_field": output_field,
        }

        upstream_ref = _find_upstream_duckdb_reference(context)
        if upstream_ref is not None:
            output[output_field] = upstream_ref
        return output


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


def _find_upstream_duckdb_reference(context: dict[str, Any]) -> dict[str, Any] | None:
    """
    Retorna a referencia DuckDB primaria upstream, se houver.

    Diferente de ``get_primary_input_reference``, esta funcao nao materializa
    nenhum dado — o no de truncate e pass-through e nao deve falhar quando
    nenhum dado chega (ex: truncate executado como primeiro passo).
    """
    upstream_results = context.get("upstream_results") or {}
    if isinstance(upstream_results, dict) and upstream_results:
        for upstream_value in reversed(list(upstream_results.values())):
            ref = find_duckdb_reference(upstream_value)
            if ref is not None:
                return ref

    # Sem referencia pronta — tenta materializar apenas se houver dados upstream
    # concretos. Caso contrario retorna None (truncate-only, sem dados a repassar).
    if isinstance(upstream_results, dict) and upstream_results:
        try:
            return get_primary_input_reference(context, "truncate_pass_through")
        except NodeProcessingError:
            return None
    return None
