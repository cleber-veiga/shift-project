"""
Processador de extracao SQL com streaming + leitura paralela particionada.

Modos de operacao
-----------------
- **Particionado** (``partition_on`` informado e ``partition_num > 1``):
  Abre N cursores server-side em paralelo, cada um cobrindo um range
  disjunto da coluna de particao. Cada cursor produz chunks que sao
  empilhados em uma queue limitada (``maxsize=4``) — backpressure natural
  entre o banco e o writer DuckDB. Acelera leituras de tabelas multi-milhao
  em 3-6x quando o banco tem indice em ``partition_on``.

- **Single-connection streaming** (``partition_on=None`` ou
  ``partition_num<=1``): mantem o caminho legacy via ``dlt`` para
  compatibilidade. Quando ``streaming=True``, usa cursor server-side e
  fetchmany — limite de RAM e o ``chunk_size``, nao o tamanho da tabela.

Garantias de seguranca
----------------------
- Coluna de particao com ``NULL`` e rejeitada — range scan deixaria linhas
  perdidas.
- ``partition_num`` e capado em ``pool_size + max_overflow`` do engine
  cacheado (engine_cache do Prompt 0.2). Sem isso, abrir N=20 conexoes
  em um pool de 10 esgota recursos do banco.
- Cancelamento cooperativo: o ``cancel_event`` interno e setado quando o
  runner abortar a execucao. Producers fecham seus cursores no proximo
  chunk; nao ha cleanup pendurado.
"""

from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.extraction_service import extraction_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


def _infer_conn_type(connection_string: str) -> str:
    cs = connection_string.lower()
    if cs.startswith(("postgresql", "postgres")):
        return "postgresql"
    if cs.startswith("mysql"):
        return "mysql"
    if cs.startswith("oracle"):
        return "oracle"
    if cs.startswith("firebird"):
        return "firebird"
    if cs.startswith(("mssql", "sqlserver")):
        return "sqlserver"
    if cs.startswith("sqlite"):
        return "sqlite"
    return "unknown"


@register_processor("sql_database")
@register_processor("extractNode")
class SqlDatabaseProcessor(BaseNodeProcessor):
    """Extrai dados SQL com streaming e (opcionalmente) leitura particionada."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        connection_string = resolved_config.get("connection_string")
        table_name = resolved_config.get("table_name")
        query = resolved_config.get("query")
        output_field = str(resolved_config.get("output_field", "data"))

        # Novos parametros de streaming/particionamento.
        partition_on_raw = resolved_config.get("partition_on")
        partition_on = (
            str(partition_on_raw).strip() if partition_on_raw else None
        ) or None
        partition_num = int(resolved_config.get("partition_num") or 1)
        chunk_size = int(resolved_config.get("chunk_size") or 50_000)
        streaming = bool(resolved_config.get("streaming", True))

        preview_max_rows: int | None = context.get("_preview_max_rows")
        configured_max_rows = resolved_config.get("max_rows")
        effective_max_rows: int | None = (
            preview_max_rows
            if preview_max_rows is not None
            else (
                int(configured_max_rows)
                if configured_max_rows is not None
                else settings.EXTRACT_DEFAULT_MAX_ROWS
            )
        )

        if not connection_string:
            raise NodeProcessingError(
                f"No SQL '{node_id}': connection_string e obrigatorio."
            )
        if not query and not table_name:
            raise NodeProcessingError(
                f"No SQL '{node_id}': informe query ou table_name."
            )

        effective_query = (
            str(query).strip()
            if query
            else f"SELECT * FROM {table_name}"
        )
        lowered = effective_query.lstrip().lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise NodeProcessingError(
                f"No SQL '{node_id}': apenas queries de extracao sao suportadas."
            )

        execution_id = str(
            context.get("execution_id")
            or context.get("workflow_id")
            or uuid4()
        )

        use_partitioned = (
            streaming
            and partition_on is not None
            and partition_num > 1
        )

        if use_partitioned:
            conn_type = _infer_conn_type(str(connection_string))
            try:
                result = extraction_service.extract_sql_partitioned_to_duckdb(
                    connection_string=str(connection_string),
                    conn_type=conn_type,
                    query=effective_query,
                    execution_id=execution_id,
                    resource_name=node_id,
                    partition_on=partition_on,
                    partition_num=partition_num,
                    chunk_size=chunk_size,
                    max_rows=effective_max_rows,
                    workspace_id=context.get("workspace_id"),
                )
            except ValueError as exc:
                # ValueError do helper de bounds (ex: coluna nullable) e
                # erro funcional — propaga como NodeProcessingError.
                raise NodeProcessingError(
                    f"No SQL '{node_id}': particionamento invalido — {exc}"
                ) from exc

            return {
                "node_id": node_id,
                "status": "completed",
                "query": effective_query,
                "output_field": output_field,
                "partition_on": partition_on,
                "partition_num": partition_num,
                "chunk_size": chunk_size,
                output_field: result.to_dict(),
            }

        # Caminho legacy: dlt + single connection. Mantido sem mudanca de
        # contrato para nao quebrar workflows existentes.
        result = extraction_service.extract_sql_to_duckdb(
            connection_string=str(connection_string),
            query=effective_query,
            execution_id=execution_id,
            resource_name=node_id,
            table_name=str(table_name) if table_name else node_id,
            max_rows=effective_max_rows,
            chunk_size=chunk_size,
        )

        return {
            "node_id": node_id,
            "status": "completed",
            "query": effective_query,
            "output_field": output_field,
            "chunk_size": chunk_size,
            output_field: result.to_dict(),
        }
