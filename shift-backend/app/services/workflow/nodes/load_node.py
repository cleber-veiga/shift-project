"""
Processador do no de carga para referencias DuckDB materializadas.

Configuracao do no:
  connection_string:  Connection string do banco de destino (obrigatorio).
  target_table:       Nome da tabela de destino, pode incluir schema (ex: VIASOFTMCP.RESUMO).
  write_disposition:  Estrategia de escrita — append (padrao), replace ou merge.
  merge_key:          Lista de colunas-chave para o UPSERT. Obrigatorio quando
                      write_disposition='merge'. Exemplo: ["NUMERO_NOTA"].
  chunk_size:         Tamanho do lote de leitura em streaming (padrao: 1000).
  output_field:       Nome do campo de saida no contexto (padrao: load_result).
"""

from typing import Any

from app.data_pipelines.duckdb_storage import build_table_ref, get_primary_input_reference
from app.data_pipelines.migrator import run_migration_pipeline
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("loadNode")
class LoadNodeProcessor(BaseNodeProcessor):
    """Carrega a tabela DuckDB upstream para o destino configurado."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        connection_string = resolved_config.get("connection_string")
        target_table = resolved_config.get("target_table")
        write_disposition = str(resolved_config.get("write_disposition", "append"))
        chunk_size = int(resolved_config.get("chunk_size", 1000))
        output_field = str(resolved_config.get("output_field", "load_result"))

        # merge_key pode ser uma lista ou uma string unica
        raw_merge_key = resolved_config.get("merge_key")
        if isinstance(raw_merge_key, str):
            merge_key = [raw_merge_key] if raw_merge_key else []
        elif isinstance(raw_merge_key, list):
            merge_key = [str(k) for k in raw_merge_key if k]
        else:
            merge_key = []

        if not connection_string:
            raise NodeProcessingError(
                f"No load '{node_id}': connection_string e obrigatorio."
            )
        if not target_table:
            raise NodeProcessingError(
                f"No load '{node_id}': target_table e obrigatorio."
            )
        if write_disposition == "merge" and not merge_key:
            raise NodeProcessingError(
                f"No load '{node_id}': merge_key e obrigatorio quando "
                f"write_disposition='merge'."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_connection = f"duckdb:///{input_reference['database_path']}"
        source_table = str(input_reference["table_name"])
        query = f"SELECT * FROM {build_table_ref(input_reference)}"

        load_result = run_migration_pipeline(
            source_connection=source_connection,
            destination_connection=str(connection_string),
            table_name=source_table,
            target_table=str(target_table),
            query=query,
            chunk_size=chunk_size,
            write_disposition=write_disposition,
            merge_key=merge_key or None,
        )

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: load_result,
        }
