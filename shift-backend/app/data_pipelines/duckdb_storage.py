"""
Utilitarios para materializacao e transformacao de dados em DuckDB.

Todos os nos de transformacao (math, filter, mapper, aggregator) usam
este modulo para ler dados upstream e escrever seus resultados.
O contrato e simples: DuckDbReference in -> operacao SQL -> DuckDbReference out.

Materializacao em streaming
---------------------------
Para fontes de dados grandes (APIs paginadas, arquivos gigantes), use
``JsonlStreamer`` em vez de ``ensure_duckdb_reference``:

    with JsonlStreamer(execution_id, node_id) as streamer:
        for batch in fonte_paginada:
            streamer.write_batch(batch)   # grava em disco imediatamente
    reference = streamer.reference        # None se nenhum dado foi escrito

A diferenca critica: ``ensure_duckdb_reference`` exige todos os dados em
memoria antes de chamar. ``JsonlStreamer`` grava em JSONL incrementalmente
e so aciona o DuckDB (CREATE TABLE AS SELECT * FROM read_json_auto)
uma unica vez ao fechar — consumindo apenas ~1 batch de RAM por vez.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import duckdb


DuckDbReference = dict[str, Any]


def ensure_duckdb_reference(
    data: Any,
    execution_id: str,
    node_id: str,
) -> DuckDbReference:
    """
    Garante que a entrada esteja materializada em DuckDB.

    Se a entrada ja for uma referencia DuckDB, ela e reutilizada. Caso seja
    uma lista/dict, ela e materializada em um banco temporario via JSONL.
    """
    existing_reference = find_duckdb_reference(data)
    if existing_reference is not None:
        return existing_reference

    if data is None:
        _raise_node_processing_error(
            f"No '{node_id}': nenhuma entrada encontrada para transformar."
        )

    rows = _coerce_rows(data)
    if not rows:
        _raise_node_processing_error(
            f"No '{node_id}': entrada vazia para transformar."
        )

    database_path = _build_duckdb_path(execution_id, node_id)
    table_name = sanitize_name(f"{node_id}_input")
    jsonl_path = database_path.with_suffix(".jsonl")

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, default=str))
            handle.write("\n")

    conn = duckdb.connect(str(database_path))
    try:
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE {quote_identifier(table_name)} AS
            SELECT * FROM read_json_auto(?, format='newline_delimited')
            """,
            [str(jsonl_path)],
        )
    finally:
        conn.close()
        jsonl_path.unlink(missing_ok=True)

    return {
        "storage_type": "duckdb",
        "database_path": str(database_path),
        "table_name": table_name,
        "dataset_name": None,
    }


def find_duckdb_reference(data: Any) -> DuckDbReference | None:
    """Procura uma referencia DuckDB em dicts aninhados de resultado.

    Preserva o campo ``dataset_name`` quando presente, pois o dlt usa um
    schema separado (ex: ``shift_extract``) dentro do arquivo ``.duckdb``.
    """
    if isinstance(data, dict):
        if data.get("storage_type") == "duckdb" and data.get("database_path"):
            return {
                "storage_type": "duckdb",
                "database_path": str(data["database_path"]),
                "table_name": str(data["table_name"]),
                "dataset_name": data.get("dataset_name"),
            }

        output_field = data.get("output_field")
        if isinstance(output_field, str) and output_field in data:
            nested = find_duckdb_reference(data[output_field])
            if nested is not None:
                return nested

        for value in data.values():
            nested = find_duckdb_reference(value)
            if nested is not None:
                return nested

    if isinstance(data, list):
        for value in data:
            nested = find_duckdb_reference(value)
            if nested is not None:
                return nested

    return None


def build_table_ref(reference: DuckDbReference) -> str:
    """
    Monta a referencia qualificada da tabela para uso em SQL DuckDB.

    Quando o dlt cria a tabela dentro de um dataset (schema), o nome
    qualificado e ``"dataset_name"."table_name"``. Sem dataset, usa apenas
    o nome da tabela.
    """
    dataset_name = reference.get("dataset_name")
    table_name = str(reference["table_name"])

    if dataset_name:
        return f"{quote_identifier(dataset_name)}.{quote_identifier(table_name)}"
    return quote_identifier(table_name)


def extract_payload(data: Any) -> Any:
    """Extrai o payload principal de um resultado de no, quando existir."""
    if isinstance(data, dict):
        output_field = data.get("output_field")
        if isinstance(output_field, str) and output_field in data:
            return data[output_field]
    return data


def get_primary_input_reference(
    context: dict[str, Any],
    node_id: str,
) -> DuckDbReference:
    """
    Resolve a referencia DuckDB principal de entrada a partir do contexto.

    Percorre os resultados upstream em ordem reversa (do mais recente para
    o mais antigo) e retorna a primeira referencia DuckDB encontrada.
    Se nenhuma referencia for encontrada, materializa o dado bruto.
    """
    upstream_results = context.get("upstream_results", {})
    execution_id = str(
        context.get("execution_id") or context.get("workflow_id") or uuid4()
    )

    if isinstance(upstream_results, dict) and upstream_results:
        for upstream_value in reversed(list(upstream_results.values())):
            duckdb_ref = find_duckdb_reference(upstream_value)
            if duckdb_ref is not None:
                return duckdb_ref

        # Nenhuma referencia DuckDB encontrada — materializa o primeiro upstream
        for upstream_value in reversed(list(upstream_results.values())):
            reference = ensure_duckdb_reference(
                extract_payload(upstream_value),
                execution_id,
                node_id,
            )
            if reference:
                return reference

    return ensure_duckdb_reference(
        extract_payload(context.get("input_data")),
        execution_id,
        node_id,
    )


def get_named_input_reference(
    context: dict[str, Any],
    node_id: str,
    handle_name: str,
) -> DuckDbReference:
    """
    Resolve a referencia DuckDB conectada a uma porta de entrada especifica.

    Usa ``context["edge_handles"]`` — mapa ``{source_node_id -> targetHandle}``
    populado pelo runner — para localizar qual no upstream chegou no handle
    informado (ex: ``"left"``, ``"right"``, ``"primary"``, ``"dictionary"``).

    Levanta NodeProcessingError quando nenhuma aresta aponta para o handle.
    """
    edge_handles: dict[str, str | None] = context.get("edge_handles", {})
    upstream_results: dict[str, Any] = context.get("upstream_results", {})
    execution_id = str(
        context.get("execution_id") or context.get("workflow_id") or uuid4()
    )

    for source_id, target_handle in edge_handles.items():
        if target_handle == handle_name:
            upstream_value = upstream_results.get(source_id)
            if upstream_value is not None:
                ref = find_duckdb_reference(upstream_value)
                if ref is not None:
                    return ref
                return ensure_duckdb_reference(
                    extract_payload(upstream_value),
                    execution_id,
                    node_id,
                )

    _raise_node_processing_error(
        f"No '{node_id}': nenhuma entrada conectada ao handle '{handle_name}'. "
        f"Handles disponiveis: {list(edge_handles.values())}"
    )
    raise AssertionError("unreachable")  # satisfaz o type-checker


def build_output_reference(
    source_reference: DuckDbReference,
    table_name: str,
) -> DuckDbReference:
    """Monta a referencia de saida apontando para a nova tabela materializada.

    A tabela de saida e sempre criada na raiz do banco (sem dataset_name),
    pois foi gerada por este no e nao pelo dlt.
    """
    return {
        "storage_type": "duckdb",
        "database_path": str(source_reference["database_path"]),
        "table_name": sanitize_name(table_name),
        "dataset_name": None,
    }


def quote_identifier(identifier: str) -> str:
    """Escapa identificadores SQL para uso seguro em DuckDB."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def sanitize_name(value: str) -> str:
    """Normaliza nomes para tabelas temporarias."""
    sanitized = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value.strip().lower()
    )
    return sanitized.strip("_") or "table"


def build_next_table_name(node_id: str, suffix: str) -> str:
    """Gera o nome da tabela de saida desta transformacao."""
    return sanitize_name(f"{node_id}_{suffix}")


def build_input_database_path(execution_id: str, node_id: str) -> Path:
    """
    Retorna (e cria) o caminho do banco DuckDB para um no de entrada.

    Usada por nos de entrada (CSV, Excel, API) que criam o banco diretamente,
    sem passar por ``ensure_duckdb_reference``.
    """
    return _build_duckdb_path(execution_id, node_id)


def _build_duckdb_path(execution_id: str, node_id: str) -> Path:
    """Cria o caminho do banco DuckDB temporario desta execucao."""
    base_dir = Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{sanitize_name(node_id)}.duckdb"


def _coerce_rows(data: Any) -> list[dict[str, Any]]:
    """Converte entradas pequenas em uma lista de dicts."""
    if isinstance(data, dict):
        return [data]

    if isinstance(data, list):
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({"value": item})
        return rows

    return [{"value": data}]


def _raise_node_processing_error(message: str) -> None:
    """Levanta NodeProcessingError sem introduzir import circular em import-time."""
    from app.services.workflow.nodes.exceptions import NodeProcessingError

    raise NodeProcessingError(message)


class JsonlStreamer:
    """
    Materializa dados em DuckDB de forma incremental, sem carregar tudo em RAM.

    Escreve linhas em um arquivo JSONL temporario em disco conforme chegam,
    e ao fechar (``__exit__``) executa um unico
    ``CREATE TABLE AS SELECT * FROM read_json_auto(...)`` para ingerir tudo
    no DuckDB de uma vez.

    Isso garante que o consumo de RAM do processo Python seja limitado ao
    tamanho do batch atual — independente do volume total de dados.

    Uso:
        execution_id = context["execution_id"]
        with JsonlStreamer(execution_id, node_id) as streamer:
            for page in paginated_source:
                streamer.write_batch(page)          # grava em disco
                if streamer.row_count > MAX:
                    break

        if streamer.reference is None:
            raise NodeProcessingError("Nenhum dado encontrado.")
        return {"node_id": node_id, "data": streamer.reference, ...}

    Atributos apos o ``with``:
        reference  : DuckDbReference pronta para uso, ou None se sem dados.
        row_count  : numero total de linhas escritas.
    """

    def __init__(self, execution_id: str, node_id: str) -> None:
        self._execution_id = execution_id
        self._node_id = node_id
        self._database_path: Path | None = None
        self._jsonl_path: Path | None = None
        self._handle: Any = None
        self._row_count: int = 0
        self.reference: DuckDbReference | None = None

    @property
    def row_count(self) -> int:
        """Numero de linhas escritas ate o momento."""
        return self._row_count

    def __enter__(self) -> "JsonlStreamer":
        self._database_path = _build_duckdb_path(self._execution_id, self._node_id)
        self._jsonl_path = self._database_path.with_suffix(".jsonl")
        self._handle = self._jsonl_path.open("w", encoding="utf-8", buffering=1 << 20)
        return self

    def write_row(self, row: dict[str, Any]) -> None:
        """Escreve uma unica linha no JSONL. Prefira ``write_batch`` quando possivel."""
        if self._handle is None:
            raise RuntimeError("JsonlStreamer nao esta aberto. Use dentro de 'with'.")
        self._handle.write(json.dumps(row, ensure_ascii=True, default=str))
        self._handle.write("\n")
        self._row_count += 1

    def write_batch(self, rows: list[dict[str, Any]]) -> None:
        """Escreve um lote de linhas no JSONL de forma eficiente."""
        if self._handle is None:
            raise RuntimeError("JsonlStreamer nao esta aberto. Use dentro de 'with'.")
        for row in rows:
            self._handle.write(json.dumps(row, ensure_ascii=True, default=str))
            self._handle.write("\n")
        self._row_count += len(rows)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Fecha o arquivo independente do resultado
        if self._handle is not None:
            self._handle.close()
            self._handle = None

        # Em caso de excecao, limpa o JSONL e nao materializa
        if exc_type is not None:
            if self._jsonl_path is not None:
                self._jsonl_path.unlink(missing_ok=True)
            return  # propaga a excecao original

        # Sem dados: nao cria tabela, reference fica None
        if self._row_count == 0 or self._jsonl_path is None:
            if self._jsonl_path is not None:
                self._jsonl_path.unlink(missing_ok=True)
            return

        table_name = sanitize_name(f"{self._node_id}_input")
        conn = duckdb.connect(str(self._database_path))
        try:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {quote_identifier(table_name)} AS
                SELECT * FROM read_json_auto(?, format='newline_delimited')
                """,
                [str(self._jsonl_path)],
            )
        finally:
            conn.close()
            self._jsonl_path.unlink(missing_ok=True)

        self.reference = {
            "storage_type": "duckdb",
            "database_path": str(self._database_path),
            "table_name": table_name,
            "dataset_name": None,
        }
