"""
Processador do no de codigo customizado.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_next_table_name,
    build_output_reference,
    get_primary_input_reference,
    quote_identifier,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("code")
class CodeNodeProcessor(BaseNodeProcessor):
    """Executa codigo Python com escopo restrito sobre uma relacao DuckDB."""

    _SAFE_BUILTINS: dict[str, Any] = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": range,
        "round": round,
        "set": set,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Extrai o codigo ANTES do resolve_data para evitar que o template
        # engine processe chaves { } dentro do codigo Python como placeholders.
        raw_code = config.get("code")
        config_without_code = {k: v for k, v in config.items() if k != "code"}
        resolved_config = self.resolve_data(config_without_code, context)

        input_reference = get_primary_input_reference(context, node_id)
        output_field = str(resolved_config.get("output_field", "data"))
        code = raw_code
        result_variable = str(resolved_config.get("result_variable", "result"))

        if not code:
            raise NodeProcessingError(f"No code '{node_id}': codigo e obrigatorio.")

        connection = duckdb.connect(str(input_reference["database_path"]))
        try:
            source_table = str(input_reference["table_name"])
            output_table = build_next_table_name(node_id, "coded")
            data = connection.table(source_table)
            local_scope: dict[str, Any] = {
                "connection": connection,
                "data": data,
                "source_table": source_table,
                "result": data,
            }

            try:
                exec(  # noqa: S102
                    str(code),
                    {"__builtins__": self._SAFE_BUILTINS},
                    local_scope,
                )
            except Exception as exc:
                raise NodeProcessingError(
                    f"No code '{node_id}': erro ao executar codigo customizado: {exc}"
                ) from exc

            result = local_scope.get(result_variable, local_scope.get("result"))
            self._materialize_result(
                connection=connection,
                result=result,
                output_table=output_table,
                source_table=source_table,
            )
        finally:
            connection.close()

        output_reference = build_output_reference(input_reference, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }

    def _materialize_result(
        self,
        connection: duckdb.DuckDBPyConnection,
        result: Any,
        output_table: str,
        source_table: str,
    ) -> None:
        """Converte o resultado do codigo para uma tabela fisica em DuckDB."""
        if isinstance(result, duckdb.DuckDBPyRelation):
            view_name = build_next_table_name(output_table, "view")
            result.create_view(view_name)
            connection.execute(
                f"""
                CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
                SELECT * FROM {quote_identifier(view_name)}
                """
            )
            return

        if isinstance(result, str):
            connection.execute(
                f"""
                CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
                {result}
                """
            )
            return

        if result is None:
            connection.execute(
                f"""
                CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
                SELECT * FROM {quote_identifier(source_table)}
                """
            )
            return

        rows = self._coerce_rows(result)
        jsonl_path = self._write_jsonl(rows, output_table)
        try:
            connection.execute(
                f"""
                CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
                SELECT * FROM read_json_auto(?, format='newline_delimited')
                """,
                [str(jsonl_path)],
            )
        finally:
            jsonl_path.unlink(missing_ok=True)

    @staticmethod
    def _coerce_rows(result: Any) -> list[dict[str, Any]]:
        """Converte o resultado do codigo em lista de linhas."""
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list):
            rows: list[dict[str, Any]] = []
            for item in result:
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    rows.append({"value": item})
            return rows
        raise NodeProcessingError(
            "Resultado do no code deve ser DuckDB relation, SQL, dict ou list."
        )

    @staticmethod
    def _write_jsonl(rows: list[dict[str, Any]], output_table: str) -> Path:
        """Persiste o resultado em JSONL temporario para carga no DuckDB."""
        temp_dir = Path(tempfile.gettempdir()) / "shift" / "code_node"
        temp_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = temp_dir / f"{output_table}.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True, default=str))
                handle.write("\n")
        return jsonl_path
