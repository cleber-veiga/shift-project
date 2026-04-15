"""
Processador do no de lookup.

Variante simplificada do join para enriquecimento de dados: adiciona colunas
de uma tabela de dicionario a tabela principal via LEFT JOIN.

Diferenca em relacao ao JoinNodeProcessor:
- Apenas LEFT JOIN, sem opcao de tipo.
- Configuracao minima: lookup_key, dictionary_key, return_columns.
- Semantica clara de "enriquecimento" na UI.

O no usa as portas de entrada ``primary`` (tabela principal) e ``dictionary``
(tabela de dicionario). O React Flow deve conectar as arestas com
``targetHandle`` correspondente para que o runner injete ``edge_handles``.

Quando as duas referencias estao em arquivos DuckDB distintos, o no realiza
ATTACH do banco de dicionario no banco principal.

Configuracao:
- lookup_key      : coluna na tabela principal usada na juncao (obrigatorio)
- dictionary_key  : coluna na tabela de dicionario usada na juncao (obrigatorio)
- return_columns  : lista de colunas do dicionario a adicionar ao resultado (obrigatorio)
- output_field    : nome do campo de saida (padrao: "data")
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

_ATTACH_ALIAS = "__lookup_dict_db__"


@register_processor("lookup")
class LookupNodeProcessor(BaseNodeProcessor):
    """Enriquece a tabela principal com colunas de uma tabela de dicionario via LEFT JOIN."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        lookup_key = resolved_config.get("lookup_key")
        dictionary_key = resolved_config.get("dictionary_key")
        return_columns: list[str] = [
            str(c) for c in (resolved_config.get("return_columns") or [])
        ]
        output_field = str(resolved_config.get("output_field", "data"))

        if not lookup_key:
            raise NodeProcessingError(
                f"No lookup '{node_id}': 'lookup_key' e obrigatorio."
            )
        if not dictionary_key:
            raise NodeProcessingError(
                f"No lookup '{node_id}': 'dictionary_key' e obrigatorio."
            )
        if not return_columns:
            raise NodeProcessingError(
                f"No lookup '{node_id}': informe ao menos uma coluna em 'return_columns'."
            )

        primary_ref = get_named_input_reference(context, node_id, "primary")
        dict_ref = get_named_input_reference(context, node_id, "dictionary")

        conn, dict_table = _open_with_dict(primary_ref, dict_ref)
        primary_table = build_table_ref(primary_ref)

        enrichment_cols = ", ".join(
            f"d.{quote_identifier(col)}" for col in return_columns
        )
        join_on = (
            f"p.{quote_identifier(str(lookup_key))} = d.{quote_identifier(str(dictionary_key))}"
        )

        output_table = sanitize_name(build_next_table_name(node_id, "enriched"))
        output_ref_sql = f"main.{quote_identifier(output_table)}"

        try:
            conn.execute(f"""
                CREATE OR REPLACE TABLE {output_ref_sql} AS
                SELECT p.*, {enrichment_cols}
                FROM {primary_table} p
                LEFT JOIN {dict_table} d ON {join_on}
            """)
        finally:
            conn.close()

        output_reference = build_output_reference(primary_ref, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }


def _open_with_dict(
    primary_ref: DuckDbReference,
    dict_ref: DuckDbReference,
) -> tuple[duckdb.DuckDBPyConnection, str]:
    """
    Abre conexao no banco principal e, se o dicionario estiver em outro arquivo,
    realiza ATTACH para permitir o JOIN entre bancos distintos.

    Retorna ``(conn, dict_table_ref)`` pronto para uso em SQL.
    """
    conn = duckdb.connect(str(primary_ref["database_path"]))

    if str(primary_ref["database_path"]) == str(dict_ref["database_path"]):
        dict_table_ref = build_table_ref(dict_ref)
    else:
        conn.execute(
            f"ATTACH '{dict_ref['database_path']}' AS {quote_identifier(_ATTACH_ALIAS)} (READ_ONLY)"
        )
        schema = dict_ref.get("dataset_name") or "main"
        table = str(dict_ref["table_name"])
        dict_table_ref = (
            f"{quote_identifier(_ATTACH_ALIAS)}"
            f".{quote_identifier(schema)}"
            f".{quote_identifier(table)}"
        )

    return conn, dict_table_ref
