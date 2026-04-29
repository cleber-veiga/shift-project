"""
Utilitarios de extracao SQL com dlt usando streaming e controle de memoria.
"""

import time
from pathlib import Path
import tempfile
from typing import Any

import dlt
import sqlalchemy as sa

_PIPELINE_MAX_RETRIES = 3
_PIPELINE_RETRY_DELAY = 0.4  # segundos; dobra a cada tentativa


def extract_sql_to_duckdb(
    connection_url: str,
    query: str,
    execution_id: str,
    resource_name: str,
    table_name: str | None = None,
    max_rows: int | None = None,
    chunk_size: int = 1000,
) -> dict[str, Any]:
    """
    Extrai dados SQL em streaming e persiste o resultado em DuckDB temporario.

    O dlt faz a carga do iterator em lotes, enquanto o SQLAlchemy le a origem
    com fetchmany para evitar que milhoes de linhas sejam carregadas de uma vez.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size deve ser maior que zero.")

    normalized_connection_url = _normalize_connection_url(connection_url)
    safe_resource_name = _sanitize_name(resource_name or "sql_extract")
    safe_table_name = _sanitize_name(table_name or safe_resource_name)
    duckdb_path = _build_duckdb_path(execution_id, safe_resource_name)
    pipelines_dir = _build_dlt_pipelines_dir(execution_id)
    pipeline_name = _sanitize_name(f"shift_extract_{execution_id}_{safe_resource_name}")
    dataset_name = "shift_extract"

    @dlt.resource(name=safe_resource_name, write_disposition="replace")
    def sql_resource() -> Any:
        """Resource dlt que pagina a leitura SQL em lotes pequenos."""
        engine = sa.create_engine(normalized_connection_url)
        total_rows = 0

        try:
            with engine.connect().execution_options(stream_results=True) as conn:
                result = conn.execute(sa.text(query))

                while True:
                    batch = result.mappings().fetchmany(chunk_size)
                    if not batch:
                        break

                    for row in batch:
                        yield dict(row)
                        total_rows += 1
                        if max_rows is not None and total_rows >= max_rows:
                            return
        finally:
            engine.dispose()

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        pipelines_dir=str(pipelines_dir),
        destination=dlt.destinations.duckdb(credentials=str(duckdb_path)),
        dataset_name=dataset_name,
        progress="log",
    )

    load_info = _run_pipeline_with_retry(
        pipeline,
        sql_resource(),
        table_name=safe_table_name,
        write_disposition="replace",
    )

    return {
        "storage_type": "duckdb",
        "pipeline_name": pipeline.pipeline_name,
        "dataset_name": dataset_name,
        "resource_name": safe_resource_name,
        "table_name": safe_table_name,
        "database_path": str(duckdb_path),
        "load_ids": list(load_info.loads_ids),
        "destination_name": str(load_info.destination_name),
    }


def _build_duckdb_path(execution_id: str, resource_name: str) -> Path:
    """Cria o caminho temporario do arquivo DuckDB desta execucao."""
    base_dir = Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{resource_name}.duckdb"


def _build_dlt_pipelines_dir(execution_id: str) -> Path:
    """Isola o workspace do dlt por execucao para evitar locks no estado global."""
    base_dir = Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id / "dlt"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _sanitize_name(value: str) -> str:
    """Normaliza nomes para uso em arquivos, dataset e tabelas."""
    sanitized = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value.strip().lower()
    )
    return sanitized.strip("_") or "resource"


def _normalize_connection_url(connection_url: str) -> str:
    """Converte drivers async para variantes sincronas quando necessario."""
    replacements = {
        "+asyncpg": "+psycopg2",
        "+aiosqlite": "",
        "+asyncmy": "+pymysql",
    }

    normalized = connection_url
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    return normalized


def _is_windows_rename_error(exc: Exception) -> bool:
    """Detecta PermissionError de rename em Windows (WinError 5 / Acesso negado).

    No Windows o Defender/Indexer abre brevemente diretórios recém-criados,
    o que faz o dlt falhar ao tentar mover arquivos de normalize/ → extracted/.
    Subir pela cadeia de causa captura o PermissionError mesmo quando o dlt
    o embrulha em PipelineStepFailed.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PermissionError):
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    # Fallback para quando dlt serializa a exceção como string na mensagem
    msg = str(exc)
    return "PermissionError" in msg and ("WinError 5" in msg or "Acesso negado" in msg or "Access is denied" in msg)


def _run_pipeline_with_retry(
    pipeline: Any,
    resource: Any,
    *,
    table_name: str,
    write_disposition: str,
) -> Any:
    """Executa pipeline.run() com retry para PermissionError de rename no Windows.

    O dlt move arquivos de normalize/ para extracted/ usando os.rename().
    No Windows isso falha intermitentemente (WinError 5) porque o Defender
    ou o Search Indexer abre o diretório recém-criado no momento exato do
    rename. Três tentativas com back-off linear cobrem a janela de ~0.5s
    do indexador.
    """
    delay = _PIPELINE_RETRY_DELAY
    for attempt in range(_PIPELINE_MAX_RETRIES):
        try:
            return pipeline.run(
                resource,
                table_name=table_name,
                write_disposition=write_disposition,
            )
        except Exception as exc:
            if _is_windows_rename_error(exc) and attempt < _PIPELINE_MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
