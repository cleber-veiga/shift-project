"""
Processador do no sql_script.

Executa SQL arbitrario (SELECT/INSERT/UPDATE/DELETE/DDL) parametrizado
contra um conector SQL, com schema de saida declarado para alimentar o
``field_mapping`` de nos downstream.

Modos suportados
----------------
- ``query``        : SELECT cujos resultados sao materializados em DuckDB
                     e expostos como ``DuckDbReference`` para nos a jusante.
- ``execute``      : INSERT/UPDATE/DELETE/DDL — reporta ``rows_affected``.
- ``execute_many`` : executa o mesmo script uma vez por linha upstream,
                     com bindings por linha (valores de parameters sao
                     nomes de colunas do upstream DuckDB).

Seguranca
---------
Bindings sao SEMPRE passados via ``text().bindparams()`` do SQLAlchemy.
O script e rejeitado quando contem placeholders de interpolacao estilo
Python format (``{nome}``) — a unica forma suportada de substituir
valores e via ``parameters``.

Nao suportado no Phase 1: transacoes multi-no, OUT params, cursores Oracle.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any
from uuid import uuid4

import duckdb
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.data_pipelines.duckdb_storage import (
    DuckDbReference,
    build_input_database_path,
    build_table_ref,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


_ALLOWED_MODES = {"query", "execute", "execute_many"}
# Detecta placeholders estilo Python ``{identificador}`` — forma proibida
# de interpolar valores no script. Use ``:nome`` + parameters.
_INTERPOLATION_PATTERN = re.compile(r"\{\s*[A-Za-z_]\w*\s*\}")


class _ScriptTimeoutError(Exception):
    """Sinaliza que a execucao do script excedeu o timeout configurado."""


@register_processor("sql_script")
class SqlScriptProcessor(BaseNodeProcessor):
    """Executa SQL arbitrario com bindings nomeados em 3 modos."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # O script e avaliado em sua forma crua para preservar placeholders
        # proibidos antes de qualquer resolucao de template.
        raw_script = str(config.get("script") or "").strip()
        if not raw_script:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': script e obrigatorio."
            )
        _assert_no_interpolation(node_id, raw_script)

        # ``parameters`` espera dotted paths (``input_data.x``, ``upstream.Y.z``)
        # que sao resolvidos adiante por ``_resolve_context_parameters``.
        # NAO rodar ``resolve_data`` sobre eles: se o usuario escrever
        # ``{{input_data.unidade}}``, o template seria pre-resolvido pro
        # valor escalar (ex.: ``"M2"``) e o resolver de parameters tentaria
        # interpretar ``"M2"`` como caminho, levantando erro confuso.
        other_config = {
            k: v for k, v in config.items() if k not in ("script", "parameters")
        }
        resolved = self.resolve_data(other_config, context)

        connection_string = resolved.get("connection_string")
        parameters_raw = config.get("parameters") or {}
        mode = str(resolved.get("mode") or "query").strip().lower()
        output_schema_raw = resolved.get("output_schema") or []
        output_field = str(resolved.get("output_field") or "sql_result")

        try:
            timeout_seconds = int(resolved.get("timeout_seconds") or 60)
        except (TypeError, ValueError) as exc:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': timeout_seconds invalido."
            ) from exc

        if not connection_string:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': connection_string e obrigatorio."
            )
        if mode not in _ALLOWED_MODES:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': modo invalido '{mode}'. "
                f"Use 'query', 'execute' ou 'execute_many'."
            )
        if not isinstance(parameters_raw, dict):
            raise NodeProcessingError(
                f"No sql_script '{node_id}': parameters deve ser um dict."
            )
        if timeout_seconds < 1:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': timeout_seconds deve ser >= 1."
            )
        if not isinstance(output_schema_raw, list):
            raise NodeProcessingError(
                f"No sql_script '{node_id}': output_schema deve ser uma lista."
            )

        parameters: dict[str, str] = {
            str(k): str(v) for k, v in parameters_raw.items()
        }

        try:
            engine = sa.create_engine(str(connection_string))
        except Exception as exc:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': falha ao abrir conexao — {exc}"
            ) from exc

        try:
            if mode == "query":
                return self._run_query(
                    node_id,
                    engine,
                    raw_script,
                    parameters,
                    output_field,
                    output_schema_raw,
                    timeout_seconds,
                    context,
                )
            if mode == "execute":
                return self._run_execute(
                    node_id,
                    engine,
                    raw_script,
                    parameters,
                    output_field,
                    timeout_seconds,
                    context,
                )
            return self._run_execute_many(
                node_id,
                engine,
                raw_script,
                parameters,
                output_field,
                timeout_seconds,
                context,
            )
        finally:
            engine.dispose()

    # ------------------------------------------------------------------
    # Modos
    # ------------------------------------------------------------------

    def _run_query(
        self,
        node_id: str,
        engine: Engine,
        script: str,
        parameters: dict[str, str],
        output_field: str,
        output_schema_raw: list[Any],
        timeout_seconds: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        bindings = self._resolve_context_parameters(node_id, parameters, context)
        statements = _split_statements(script)
        if not statements:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': nenhum statement no script."
            )

        def _execute() -> tuple[list[str], list[tuple[Any, ...]]]:
            with engine.connect() as conn:
                for prev in statements[:-1]:
                    conn.execute(sa.text(prev), bindings)
                last_result = conn.execute(sa.text(statements[-1]), bindings)
                if not last_result.returns_rows:
                    return [], []
                cols = list(last_result.keys())
                rows = [tuple(r) for r in last_result.fetchall()]
                return cols, rows

        columns, rows = _invoke_with_timeout(node_id, _execute, timeout_seconds)

        if not columns:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': modo 'query' requer um SELECT "
                f"no ultimo statement — use 'execute' para scripts sem retorno."
            )

        declared = _parse_output_schema(node_id, output_schema_raw)
        if declared:
            declared_names = [d["name"] for d in declared]
            if [c.lower() for c in columns] != [n.lower() for n in declared_names]:
                raise NodeProcessingError(
                    f"No sql_script '{node_id}': output_schema declarado "
                    f"{declared_names} nao corresponde as colunas "
                    f"retornadas {columns}."
                )

        execution_id = str(
            context.get("execution_id") or context.get("workflow_id") or uuid4()
        )
        reference = _materialize_to_duckdb(
            execution_id, node_id, columns, rows
        )

        return {
            "node_id": node_id,
            "status": "completed",
            "row_count": len(rows),
            "output_field": output_field,
            output_field: {
                "reference": reference,
                "row_count": len(rows),
            },
        }

    def _run_execute(
        self,
        node_id: str,
        engine: Engine,
        script: str,
        parameters: dict[str, str],
        output_field: str,
        timeout_seconds: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        bindings = self._resolve_context_parameters(node_id, parameters, context)
        statements = _split_statements(script)
        if not statements:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': nenhum statement no script."
            )

        def _execute() -> int:
            total = 0
            with engine.begin() as conn:
                for stmt in statements:
                    result = conn.execute(sa.text(stmt), bindings)
                    rc = result.rowcount
                    if rc is not None and rc >= 0:
                        total += rc
            return total

        rows_affected = _invoke_with_timeout(node_id, _execute, timeout_seconds)

        return {
            "node_id": node_id,
            "status": "completed",
            "rows_affected": rows_affected,
            "output_field": output_field,
            output_field: {"rows_affected": rows_affected},
        }

    def _run_execute_many(
        self,
        node_id: str,
        engine: Engine,
        script: str,
        parameters: dict[str, str],
        output_field: str,
        timeout_seconds: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if not parameters:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': modo 'execute_many' requer "
                f"parameters referenciando colunas upstream."
            )

        upstream_ref = get_primary_input_reference(context, node_id)
        upstream_columns = sorted({v for v in parameters.values() if v.strip()})
        if not upstream_columns:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': modo 'execute_many' requer "
                f"pelo menos um parametro com nome de coluna upstream."
            )

        rows = _read_upstream_rows(upstream_ref, upstream_columns)
        statements = _split_statements(script)
        if not statements:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': nenhum statement no script."
            )

        def _execute() -> int:
            total = 0
            with engine.begin() as conn:
                for row in rows:
                    bindings: dict[str, Any] = {
                        name: row.get(col) for name, col in parameters.items()
                    }
                    for stmt in statements:
                        result = conn.execute(sa.text(stmt), bindings)
                        rc = result.rowcount
                        if rc is not None and rc >= 0:
                            total += rc
            return total

        rows_affected = _invoke_with_timeout(node_id, _execute, timeout_seconds)

        return {
            "node_id": node_id,
            "status": "completed",
            "rows_affected": rows_affected,
            "rows_processed": len(rows),
            "output_field": output_field,
            output_field: {
                "rows_affected": rows_affected,
                "rows_processed": len(rows),
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_context_parameters(
        self,
        node_id: str,
        parameters: dict[str, str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve valores como dotted paths no contexto.

        Convencao: ``upstream.X.Y`` e alias para ``upstream_results.X.Y``.
        Valores que nao referenciam o contexto (ex: ``None``) caem para
        literal apenas quando a string inteira nao pode ser interpretada
        como path — senao levanta NodeProcessingError.
        """
        resolved: dict[str, Any] = {}
        for name, raw_path in parameters.items():
            path = raw_path.strip()
            if not path:
                raise NodeProcessingError(
                    f"No sql_script '{node_id}': parametro '{name}' "
                    f"tem valor vazio."
                )
            lookup_path = path
            if lookup_path.startswith("upstream."):
                lookup_path = "upstream_results." + lookup_path[len("upstream."):]
            value = self._resolve_path(lookup_path, context)
            if value is None:
                raise NodeProcessingError(
                    f"No sql_script '{node_id}': parametro '{name}' "
                    f"nao pode ser resolvido a partir de '{path}'."
                )
            resolved[name] = value
        return resolved


# ----------------------------------------------------------------------
# Funcoes auxiliares (modulo-level — facilita testes unitarios isolados)
# ----------------------------------------------------------------------


def _assert_no_interpolation(node_id: str, script: str) -> None:
    match = _INTERPOLATION_PATTERN.search(script)
    if match:
        raise NodeProcessingError(
            f"No sql_script '{node_id}': placeholder '{match.group(0)}' "
            f"detectado no script. Use bindings ':nome' + parameters — "
            f"interpolacao de string nao e permitida."
        )


def _split_statements(script: str) -> list[str]:
    """Divide o script em statements, ignorando ``;`` dentro de literais."""
    statements: list[str] = []
    buffer: list[str] = []
    in_single = False
    in_double = False
    for ch in script:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == ";" and not in_single and not in_double:
            stmt = "".join(buffer).strip()
            if stmt:
                statements.append(stmt)
            buffer = []
        else:
            buffer.append(ch)
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _parse_output_schema(
    node_id: str, raw: list[Any],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise NodeProcessingError(
                f"No sql_script '{node_id}': output_schema deve conter "
                f"objetos com 'name' e 'type'."
            )
        name = str(entry.get("name") or "").strip()
        type_ = str(entry.get("type") or "").strip()
        if not name or not type_:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': cada item de output_schema "
                f"requer 'name' e 'type' nao vazios."
            )
        result.append({"name": name, "type": type_})
    return result


def _invoke_with_timeout(node_id: str, func: Any, timeout_seconds: int) -> Any:
    """Executa ``func`` em thread isolada aplicando o timeout informado."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(func)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as exc:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': execucao excedeu "
                f"{timeout_seconds}s (timeout)."
            ) from exc
        except SQLAlchemyError as exc:
            raise NodeProcessingError(
                f"No sql_script '{node_id}': falha ao executar script — {exc}"
            ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _materialize_to_duckdb(
    execution_id: str,
    node_id: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> DuckDbReference:
    """Materializa ``rows`` em uma tabela DuckDB temporaria."""
    database_path = build_input_database_path(execution_id, node_id)
    table_name = sanitize_name(f"{node_id}_sql_result")
    table_ref = f"main.{quote_identifier(table_name)}"
    col_types = _infer_column_types(columns, rows)
    col_defs = ", ".join(
        f"{quote_identifier(c)} {col_types[c]}" for c in columns
    )

    conn = duckdb.connect(str(database_path))
    try:
        conn.execute(f"CREATE OR REPLACE TABLE {table_ref} ({col_defs})")
        if rows:
            placeholders = ", ".join(["?"] * len(columns))
            insert_sql = f"INSERT INTO {table_ref} VALUES ({placeholders})"
            for row in rows:
                conn.execute(insert_sql, list(row))
    finally:
        conn.close()

    return {
        "storage_type": "duckdb",
        "database_path": str(database_path),
        "table_name": table_name,
        "dataset_name": None,
    }


def _infer_column_types(
    columns: list[str], rows: list[tuple[Any, ...]]
) -> dict[str, str]:
    """Deriva tipos DuckDB a partir da primeira linha nao nula por coluna."""
    types: dict[str, str] = {c: "VARCHAR" for c in columns}
    for idx, col in enumerate(columns):
        for row in rows:
            val = row[idx]
            if val is None:
                continue
            if isinstance(val, bool):
                types[col] = "BOOLEAN"
            elif isinstance(val, int):
                types[col] = "BIGINT"
            elif isinstance(val, float):
                types[col] = "DOUBLE"
            else:
                types[col] = "VARCHAR"
            break
    return types


def _read_upstream_rows(
    reference: DuckDbReference,
    columns: list[str],
) -> list[dict[str, Any]]:
    """Le apenas as colunas necessarias do DuckDB upstream."""
    if not columns:
        return []
    table_ref = build_table_ref(reference)
    projection = ", ".join(quote_identifier(c) for c in columns)
    conn = duckdb.connect(str(reference["database_path"]), read_only=True)
    try:
        cursor = conn.execute(f"SELECT {projection} FROM {table_ref}")
        fetched_cols = [desc[0] for desc in cursor.description]
        return [dict(zip(fetched_cols, row)) for row in cursor.fetchall()]
    finally:
        conn.close()
