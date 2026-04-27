"""
Processador do no de codigo customizado.

Modo de execucao
----------------
- **Sandbox Docker** (recomendado em SaaS multi-tenant): quando
  ``settings.SANDBOX_ENABLED = True`` ou ``config["sandbox"] = True``,
  o codigo do usuario roda dentro de um container efemero via
  ``app.services.sandbox.docker_sandbox.run_user_code``. Isolamento por
  cgroups + network=none + read-only FS. Ver ``kernel-runtime/`` para a
  imagem.
- **In-process** (legacy, desenvolvimento single-tenant): cai no caminho
  ``exec`` original com builtins restritos. NAO USAR EM PRODUCAO
  multi-tenant — qualquer cliente pode ler memoria/disco do host.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_input_database_path,
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

        # Roteamento: sandbox Docker quando habilitado globalmente OU
        # opt-in explicito por node. Evitar import circular: lazy import.
        from app.core.config import settings as _settings

        sandbox_enabled = bool(
            resolved_config.get("sandbox", _settings.SANDBOX_ENABLED)
        )
        if sandbox_enabled:
            return self._process_in_sandbox(
                node_id=node_id,
                code=str(code),
                input_reference=input_reference,
                output_field=output_field,
                config=resolved_config,
                context=context,
            )

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

    def _process_in_sandbox(
        self,
        node_id: str,
        code: str,
        input_reference: dict[str, Any],
        output_field: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Executa ``code`` dentro de um container Docker efemero.

        Materializa a tabela de entrada como Parquet em um tmpdir do host
        (montado read-only em ``/input`` no container), recupera o
        ``/output/result.parquet`` e o ingere de volta em DuckDB para
        manter o contrato ``DuckDbReference`` esperado pelos nodes a jusante.
        """
        from app.core.config import settings as _settings
        from app.services.sandbox import (
            SandboxLimits,
            SandboxUnavailable,
            run_user_code,
        )

        # Caps locais — clipados pelo workspace e pelos absolutos do platform
        # dentro de ``run_user_code``. Aceita override por node mas nao por
        # tenant via UI publica.
        limits = SandboxLimits(
            cpu_quota=float(config.get("cpu_quota", _settings.SANDBOX_DEFAULT_CPU_QUOTA)),
            mem_limit_mb=int(config.get("mem_limit_mb", _settings.SANDBOX_DEFAULT_MEM_LIMIT_MB)),
            timeout_s=int(config.get("timeout_s", _settings.SANDBOX_DEFAULT_TIMEOUT_S)),
            tmpfs_mb=int(config.get("tmpfs_mb", _settings.SANDBOX_DEFAULT_TMPFS_MB)),
            pids_limit=int(config.get("pids_limit", _settings.SANDBOX_DEFAULT_PIDS_LIMIT)),
        )

        execution_id = str(context.get("execution_id") or node_id)
        # Materializa a tabela DuckDB de entrada como parquet em um tmpdir
        # *do host* — o container monta esse arquivo em /input/table.parquet.
        # NUNCA passamos o database_path original; isolamento por copia.
        input_parquet = self._dump_input_to_parquet(input_reference, execution_id, node_id)

        try:
            sandbox_result = asyncio.run(
                run_user_code(
                    code=code,
                    input_table=input_parquet,
                    limits=limits,
                    execution_id=f"{execution_id}-{node_id}",
                )
            )
        except SandboxUnavailable as exc:
            raise NodeProcessingError(
                f"No code '{node_id}': sandbox Docker indisponivel — {exc}. "
                "Verifique se o daemon esta rodando e se a imagem "
                f"{_settings.SANDBOX_IMAGE} foi construida."
            ) from exc
        finally:
            try:
                input_parquet.unlink(missing_ok=True)
            except OSError:
                pass

        if not sandbox_result.success:
            detail = sandbox_result.stderr.strip() or sandbox_result.error or "erro desconhecido"
            if sandbox_result.timed_out:
                raise NodeProcessingError(
                    f"No code '{node_id}': execucao excedeu o timeout "
                    f"({limits.timeout_s}s). stdout/stderr capturados foram descartados."
                )
            if sandbox_result.oom_killed:
                raise NodeProcessingError(
                    f"No code '{node_id}': execucao usou mais que "
                    f"{limits.mem_limit_mb}MB e foi morta pelo cgroup."
                )
            raise NodeProcessingError(
                f"No code '{node_id}': sandbox retornou exit_code="
                f"{sandbox_result.exit_code}. stderr:\n{detail[:2000]}"
            )

        if sandbox_result.output_path is None:
            raise NodeProcessingError(
                f"No code '{node_id}': sandbox finalizou com sucesso mas nao "
                "produziu /output/result.parquet."
            )

        # Ingere o parquet de volta em DuckDB para preservar o contrato
        # DuckDbReference esperado pelos nodes downstream.
        output_table = build_next_table_name(node_id, "coded")
        output_db = build_input_database_path(execution_id, f"{node_id}_sandbox_out")
        ingest_conn = duckdb.connect(str(output_db))
        try:
            ingest_conn.execute(
                f"""
                CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
                SELECT * FROM read_parquet(?)
                """,
                [str(sandbox_result.output_path)],
            )
        finally:
            ingest_conn.close()
            # Apos ingerir, o parquet do sandbox nao serve mais a ninguem.
            try:
                sandbox_result.output_path.unlink(missing_ok=True)
            except OSError:
                pass

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            "duration_ms": int(sandbox_result.duration_s * 1000),
            "stdout": sandbox_result.stdout,
            output_field: {
                "storage_type": "duckdb",
                "database_path": str(output_db),
                "table_name": output_table,
                "dataset_name": None,
            },
        }

    @staticmethod
    def _dump_input_to_parquet(
        input_reference: dict[str, Any],
        execution_id: str,
        node_id: str,
    ) -> Path:
        """Exporta a tabela DuckDB de entrada para parquet num tmpdir do host."""
        tmp_root = Path(tempfile.gettempdir()) / "shift" / "sandbox-inputs" / execution_id
        tmp_root.mkdir(parents=True, exist_ok=True)
        out_path = tmp_root / f"{node_id}_input.parquet"

        src_db = str(input_reference["database_path"])
        src_table = str(input_reference["table_name"])
        src_dataset = input_reference.get("dataset_name")
        qualified = (
            f"{quote_identifier(str(src_dataset))}.{quote_identifier(src_table)}"
            if src_dataset
            else quote_identifier(src_table)
        )

        # ``read_only=True`` removido — vide filter_node sobre incompat de
        # configs concorrentes; copiamos para parquet, default RW funciona.
        conn = duckdb.connect(src_db)
        try:
            conn.execute(
                f"COPY (SELECT * FROM {qualified}) TO ? (FORMAT PARQUET)",
                [str(out_path)],
            )
        finally:
            conn.close()
        return out_path

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
