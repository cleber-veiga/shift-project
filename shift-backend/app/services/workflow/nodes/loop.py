"""
Processador do no ``loop`` — iteracao sobre dataset chamando sub-workflow.

Para cada item do dataset upstream, invoca a ``WorkflowVersion`` publicada
indicada em ``workflow_id`` + ``workflow_version``. O item entra como input
do sub-workflow via ``item_param_name`` (obrigatorio); opcionalmente um
indice 0-based pode ser passado via ``index_param_name``. Outros inputs
do sub-workflow podem vir de ``extra_inputs`` — dotted paths resolvidos
contra o contexto do loop (mesma logica dos templates).

Modos
-----
- ``sequential`` : uma iteracao por vez (default). Cada iteracao e isolada
  da anterior: NAO ha estado compartilhado entre iteracoes; se um caso
  de uso precisa disso, esta abusando do loop (use tabela externa).
- ``parallel``   : iteracoes em paralelo, limitadas por ``max_parallelism``
  via ``asyncio.Semaphore``.

Politicas de erro
-----------------
- ``fail_fast`` : primeira falha aborta o loop.
- ``continue``  : falhas sao ignoradas silenciosamente — so os sucessos
  aparecem no resultado.
- ``collect``   : resultado contem ``successes`` + ``failures`` (cada
  failure carrega ``index``, ``item`` e ``error``).

Loops aninhados (proibidos)
---------------------------
Se este processor roda com ``context['in_loop'] is True``, ja estamos
dentro de outra iteracao — rejeitamos imediatamente. A marca ``in_loop``
e propagada via ``run_workflow(in_loop=True)`` no execution_context.

Streaming
---------
Datasets DuckDB sao lidos em chunks de 1000 linhas; listas inline sao
consumidas de uma vez (ja estao em memoria). ``max_iterations`` limita
quantidade total — datasets maiores sao rejeitados antes de comecar.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import duckdb

from app.data_pipelines.duckdb_storage import (
    DuckDbReference,
    build_table_ref,
    find_duckdb_reference,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.nodes.sub_workflow import _invoke_subworkflow


_CHUNK_SIZE = 1000


@register_processor("loop")
class LoopProcessor(BaseNodeProcessor):
    """Itera sobre um dataset invocando um sub-workflow por item."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if context.get("in_loop"):
            raise NodeProcessingError(
                f"No loop '{node_id}': loops aninhados nao sao permitidos. "
                "Extraia a logica iterativa para um sub-workflow ou use sql_script."
            )

        cfg = self._validate_config(node_id, config)
        source_value = self._resolve_path(cfg["source_field"], context)
        if source_value is None:
            raise NodeProcessingError(
                f"No loop '{node_id}': source_field '{cfg['source_field']}' "
                "nao pode ser resolvido no contexto."
            )

        items = self._materialize_items(node_id, source_value, cfg["max_iterations"])
        if not items:
            return _build_output(cfg, successes=[], failures=[], total=0)

        call_stack = list(context.get("call_stack") or [])
        # Resolve extra_inputs UMA vez (nao depende do item corrente).
        base_inputs: dict[str, Any] = {}
        for name, path in cfg["extra_inputs"].items():
            if isinstance(path, str):
                base_inputs[name] = self.resolve_template(path, context)
            else:
                base_inputs[name] = path

        return asyncio.run(
            _run_iterations(
                node_id=node_id,
                cfg=cfg,
                items=items,
                base_inputs=base_inputs,
                call_stack=call_stack,
            )
        )

    # ------------------------------------------------------------------
    # Validacao e materializacao do dataset
    # ------------------------------------------------------------------

    def _validate_config(self, node_id: str, config: dict[str, Any]) -> dict[str, Any]:
        required = ("source_field", "workflow_id", "item_param_name")
        for key in required:
            if not config.get(key):
                raise NodeProcessingError(
                    f"No loop '{node_id}': '{key}' e obrigatorio."
                )

        try:
            workflow_id = UUID(str(config["workflow_id"]))
        except (TypeError, ValueError) as exc:
            raise NodeProcessingError(
                f"No loop '{node_id}': workflow_id invalido."
            ) from exc

        mode = str(config.get("mode") or "sequential").lower()
        if mode not in ("sequential", "parallel"):
            raise NodeProcessingError(
                f"No loop '{node_id}': mode invalido '{mode}'."
            )

        on_err = str(config.get("on_item_error") or "fail_fast").lower()
        if on_err not in ("fail_fast", "continue", "collect"):
            raise NodeProcessingError(
                f"No loop '{node_id}': on_item_error invalido '{on_err}'."
            )

        max_iter = int(config.get("max_iterations") or 10_000)
        if max_iter < 1:
            raise NodeProcessingError(
                f"No loop '{node_id}': max_iterations deve ser >= 1."
            )

        max_par = int(config.get("max_parallelism") or 4)
        if max_par < 1:
            raise NodeProcessingError(
                f"No loop '{node_id}': max_parallelism deve ser >= 1."
            )

        extra = config.get("extra_inputs") or {}
        if not isinstance(extra, dict):
            raise NodeProcessingError(
                f"No loop '{node_id}': extra_inputs deve ser um dict."
            )

        return {
            "source_field": str(config["source_field"]),
            "workflow_id": workflow_id,
            "workflow_version": config.get("workflow_version", "latest"),
            "item_param_name": str(config["item_param_name"]),
            "index_param_name": (
                str(config["index_param_name"]) if config.get("index_param_name") else None
            ),
            "extra_inputs": {str(k): v for k, v in extra.items()},
            "mode": mode,
            "max_parallelism": max_par,
            "on_item_error": on_err,
            "max_iterations": max_iter,
            "output_field": str(config.get("output_field") or "loop_result"),
            "timeout_seconds": int(config.get("timeout_seconds") or 300),
        }

    def _materialize_items(
        self,
        node_id: str,
        source_value: Any,
        max_iterations: int,
    ) -> list[dict[str, Any]]:
        """Resolve o source para uma lista de dicts.

        Aceita referencia DuckDB (direta ou aninhada) ou lista inline. Um
        dict sem ``storage_type`` e tratado como um unico item.
        """
        reference = find_duckdb_reference(source_value)
        if reference is not None:
            return _read_duckdb_rows(reference, max_iterations, node_id)

        if isinstance(source_value, list):
            if len(source_value) > max_iterations:
                raise NodeProcessingError(
                    f"No loop '{node_id}': dataset possui {len(source_value)} "
                    f"itens, maior que max_iterations={max_iterations}."
                )
            items: list[dict[str, Any]] = []
            for idx, raw in enumerate(source_value):
                if not isinstance(raw, dict):
                    items.append({"value": raw})
                else:
                    items.append(dict(raw))
            return items

        if isinstance(source_value, dict):
            return [dict(source_value)]

        raise NodeProcessingError(
            f"No loop '{node_id}': source_field deve resolver para lista, "
            "dict ou DuckDbReference."
        )


def _read_duckdb_rows(
    reference: DuckDbReference,
    max_iterations: int,
    node_id: str,
) -> list[dict[str, Any]]:
    """Le todas as linhas (ate max_iterations) do DuckDB em chunks."""
    table_ref = build_table_ref(reference)
    conn = duckdb.connect(str(reference["database_path"]), read_only=True)
    try:
        count_row = conn.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()
        total = int(count_row[0]) if count_row else 0
        if total > max_iterations:
            raise NodeProcessingError(
                f"No loop '{node_id}': dataset possui {total} linhas, "
                f"maior que max_iterations={max_iterations}."
            )

        rows: list[dict[str, Any]] = []
        offset = 0
        while offset < total:
            cursor = conn.execute(
                f"SELECT * FROM {table_ref} LIMIT {_CHUNK_SIZE} OFFSET {offset}"
            )
            columns = [desc[0] for desc in cursor.description]
            chunk = cursor.fetchall()
            for row in chunk:
                rows.append(dict(zip(columns, row)))
            offset += len(chunk)
            if not chunk:
                break
        return rows
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Execucao das iteracoes
# ---------------------------------------------------------------------------


async def _run_iterations(
    *,
    node_id: str,
    cfg: dict[str, Any],
    items: list[dict[str, Any]],
    base_inputs: dict[str, Any],
    call_stack: list[str],
) -> dict[str, Any]:
    """Roteia para execucao sequencial ou paralela conforme cfg['mode']."""
    results: list[dict[str, Any] | None] = [None] * len(items)
    failures: list[dict[str, Any]] = []
    first_error: Exception | None = None

    async def _run_one(idx: int, item: dict[str, Any]) -> None:
        nonlocal first_error
        if first_error is not None and cfg["on_item_error"] == "fail_fast":
            return
        inputs = dict(base_inputs)
        inputs[cfg["item_param_name"]] = item
        if cfg["index_param_name"]:
            inputs[cfg["index_param_name"]] = idx
        try:
            sub = await _invoke_subworkflow(
                node_id=node_id,
                target_workflow_id=cfg["workflow_id"],
                version_spec=cfg["workflow_version"],
                mapped_inputs=inputs,
                call_stack=call_stack,
                timeout_seconds=cfg["timeout_seconds"],
                in_loop=True,
            )
            results[idx] = sub["workflow_output"]
        except Exception as exc:  # noqa: BLE001 — propagado via politica
            if cfg["on_item_error"] == "fail_fast":
                if first_error is None:
                    first_error = exc
                return
            failures.append({
                "index": idx,
                "item": item,
                "error": str(exc),
            })

    if cfg["mode"] == "sequential":
        for idx, item in enumerate(items):
            await _run_one(idx, item)
            if first_error is not None:
                break
    else:
        sem = asyncio.Semaphore(cfg["max_parallelism"])

        async def _guarded(idx: int, item: dict[str, Any]) -> None:
            async with sem:
                await _run_one(idx, item)

        await asyncio.gather(*[_guarded(i, it) for i, it in enumerate(items)])

    if first_error is not None:
        raise NodeProcessingError(
            f"No loop '{node_id}': item 0-based abortou o loop (fail_fast) — {first_error}"
        ) from first_error

    successes = [r for r in results if r is not None]
    return _build_output(cfg, successes=successes, failures=failures, total=len(items))


def _build_output(
    cfg: dict[str, Any],
    *,
    successes: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    total: int,
) -> dict[str, Any]:
    """Monta o dict final conforme a politica de erro."""
    output_field = cfg["output_field"]
    if cfg["on_item_error"] == "collect":
        payload: dict[str, Any] = {
            "successes": successes,
            "failures": failures,
            "total": total,
        }
    else:
        payload = {
            "items": successes,
            "total": total,
            "error_count": len(failures),
        }

    return {
        "status": "completed",
        "iterations": total,
        "successes": len(successes),
        "failures": len(failures),
        "output_field": output_field,
        output_field: payload,
    }
