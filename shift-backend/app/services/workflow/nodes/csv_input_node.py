"""
Processador do no de entrada CSV.

Lê um arquivo CSV local ou remoto (http/https/s3) diretamente no DuckDB
usando ``read_csv_auto`` — sem buffer intermediario em Python.

O DuckDB transmite o arquivo linha a linha, tornando esta abordagem
eficiente em memoria mesmo para arquivos de varios gigabytes.
Para URLs remotas, o DuckDB usa a extensao ``httpfs`` internamente.

Configuracao:
- url          : caminho local ou URL do arquivo (obrigatorio)
- delimiter    : separador de colunas (padrao: ",")
- has_header   : se a primeira linha e o cabecalho (padrao: true)
- encoding     : codificacao do arquivo (padrao: "utf-8")
- null_padding : preenche colunas faltantes com NULL (padrao: true)
- output_field : nome do campo de saida (padrao: "data")
"""

from typing import Any
from uuid import uuid4

import duckdb

from app.core.config import settings
from app.data_pipelines.duckdb_storage import (
    DuckDbReference,
    build_input_database_path,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes._input_helpers import (
    resolve_upload_url,
    validate_against_input_model,
)
from app.services.workflow.nodes.exceptions import NodeProcessingError

# Encodings aceitos para evitar injecao de parametros arbitrarios no SQL
_KNOWN_ENCODINGS = {
    "utf-8", "utf-16", "utf-16-le", "utf-16-be",
    "latin-1", "iso-8859-1", "cp1252", "ascii",
}

# Prefixos que indicam URL remota e exigem httpfs
_REMOTE_PREFIXES = ("http://", "https://", "s3://", "gs://", "azure://")


@register_processor("csv_input")
class CsvInputNodeProcessor(BaseNodeProcessor):
    """Le um CSV local ou remoto e materializa em DuckDB via read_csv_auto."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        url = resolved_config.get("url")
        delimiter = str(resolved_config.get("delimiter", ","))
        has_header = bool(resolved_config.get("has_header", True))
        encoding = str(resolved_config.get("encoding", "utf-8")).lower()
        null_padding = bool(resolved_config.get("null_padding", True))
        output_field = str(resolved_config.get("output_field", "data"))
        preview_max_rows: int | None = context.get("_preview_max_rows")
        configured_max_rows = resolved_config.get("max_rows")
        max_rows: int | None = (
            preview_max_rows
            if preview_max_rows is not None
            else (int(configured_max_rows) if configured_max_rows is not None else settings.EXTRACT_DEFAULT_MAX_ROWS)
        )

        if not url:
            raise NodeProcessingError(
                f"No csv_input '{node_id}': 'url' e obrigatorio."
            )
        # Resolve URI shift-upload://<file_id> antes da validacao de
        # delimitador/encoding pra que erros de upload tenham prioridade.
        url = resolve_upload_url(node_id, str(url), context)
        if len(delimiter) != 1:
            raise NodeProcessingError(
                f"No csv_input '{node_id}': 'delimiter' deve ser um unico caractere."
            )
        if encoding not in _KNOWN_ENCODINGS:
            raise NodeProcessingError(
                f"No csv_input '{node_id}': encoding '{encoding}' nao suportado. "
                f"Opcoes: {sorted(_KNOWN_ENCODINGS)}"
            )

        execution_id = str(
            context.get("execution_id") or context.get("workflow_id") or uuid4()
        )
        database_path = build_input_database_path(execution_id, node_id)
        table_name = sanitize_name(f"{node_id}_csv")
        output_ref = f"main.{quote_identifier(table_name)}"

        # Escapa para uso seguro em SQL (sem parameterizacao de opcoes no DuckDB)
        delimiter_sql = delimiter.replace("'", "''")
        encoding_sql = encoding.replace("'", "''")
        header_sql = "true" if has_header else "false"
        null_padding_sql = "true" if null_padding else "false"

        limit_clause = f"LIMIT {max_rows}" if max_rows is not None else ""

        conn = duckdb.connect(str(database_path))
        try:
            # Para URLs remotas, tenta carregar a extensao httpfs
            _ensure_httpfs(conn, str(url))

            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref} AS
                SELECT * FROM read_csv_auto(
                    ?,
                    delim        = '{delimiter_sql}',
                    header       = {header_sql},
                    encoding     = '{encoding_sql}',
                    null_padding = {null_padding_sql}
                )
                {limit_clause}
                """,
                [str(url)],
            )
            row_count = conn.execute(
                f"SELECT COUNT(*) FROM {output_ref}"
            ).fetchone()[0]

            # Valida contra InputModel vinculado, se existir.
            input_model_id = resolved_config.get("input_model_id")
            if input_model_id:
                actual_columns = [
                    row[0]
                    for row in conn.execute(
                        f"DESCRIBE {output_ref}"
                    ).fetchall()
                ]
                validate_against_input_model(
                    node_id=node_id,
                    input_model_id=str(input_model_id),
                    actual_columns=actual_columns,
                )
        except NodeProcessingError:
            raise
        except Exception as exc:
            raise NodeProcessingError(
                f"No csv_input '{node_id}': falha ao ler CSV — {exc}"
            ) from exc
        finally:
            conn.close()

        if row_count == 0:
            raise NodeProcessingError(
                f"No csv_input '{node_id}': arquivo CSV nao continha linhas de dados."
            )

        reference: DuckDbReference = {
            "storage_type": "duckdb",
            "database_path": str(database_path),
            "table_name": table_name,
            "dataset_name": None,
        }
        return {
            "node_id": node_id,
            "status": "completed",
            "row_count": row_count,
            "output_field": output_field,
            output_field: reference,
        }


def _ensure_httpfs(conn: duckdb.DuckDBPyConnection, url: str) -> None:
    """Tenta carregar a extensao httpfs para leitura de URLs remotas."""
    if any(url.lower().startswith(prefix) for prefix in _REMOTE_PREFIXES):
        try:
            conn.execute("LOAD httpfs")
        except Exception:
            # Pode estar ja carregada ou nao instalada — deixa o DuckDB
            # lidar com isso ao executar a query.
            pass
