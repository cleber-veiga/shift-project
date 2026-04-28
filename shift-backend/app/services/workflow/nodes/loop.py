"""
Processador do no ``loop`` — iteracao sobre dataset.

Dois modos de corpo de iteracao:

- ``body_mode='external'`` (padrao): para cada item, invoca a
  ``WorkflowVersion`` publicada em ``workflow_id`` + ``workflow_version``.
  Mantem-se compativel com workflows existentes (sem ``body_mode`` cai
  aqui).
- ``body_mode='inline'``: o corpo do loop e um subgrafo embutido em
  ``body = {nodes, edges}`` no proprio ``data`` do no. A cada iteracao,
  o subgrafo roda via ``run_workflow`` recebendo ``item`` e ``idx`` no
  ``input_data``. Ideal pra "rodar 1-2 nos por item" sem precisar
  publicar um sub-workflow separado.

Modos de mapeamento de inputs
-----------------------------
1) **input_mapping** (recomendado, UX estilo call_workflow): dict
   ``{param_name: template}`` onde cada template e resolvido por iteracao
   contra o contexto estendido com ``item`` + ``idx``. Permite mapear
   campos individuais do item para parametros individuais do sub-workflow.
   Ex.: ``{"unidade": "{{item.cod_unidade}}", "descricao": "{{item.desc}}"}``.

2) **Legado** (``item_param_name`` + ``index_param_name`` + ``extra_inputs``):
   o item INTEIRO vai para ``item_param_name``; opcional indice 0-based em
   ``index_param_name``. ``extra_inputs`` carrega dotted paths resolvidos
   uma unica vez antes das iteracoes (constantes).

Se ``input_mapping`` esta presente e nao-vazio, ele TEM PRECEDENCIA e o
modo legado e ignorado.

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
import concurrent.futures
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import duckdb

from app.data_pipelines.duckdb_storage import (
    DuckDbReference,
    build_table_ref,
    find_duckdb_reference,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.nodes.sub_workflow import _invoke_subworkflow

_BODY_MODE_EXTERNAL = "external"
_BODY_MODE_INLINE = "inline"
_BODY_MODES = (_BODY_MODE_EXTERNAL, _BODY_MODE_INLINE)


# Tipos que NUNCA podem aparecer dentro de um body inline.
# Triggers nao fazem sentido (cada iteracao nao e um trigger), nem
# ``loop`` aninhado (proibido por contrato), nem ``workflow_input/output``
# (essas sao convencoes de sub-workflow externo).
_BODY_FORBIDDEN_NODE_TYPES = frozenset({
    "loop",
    "manual_trigger",
    "cron_trigger",
    "schedule_trigger",
    "webhook_trigger",
    "polling_trigger",
    "api_input_node",
    "workflow_input",
    "workflow_output",
    # Variantes legadas de tipo no campo "type" do React Flow:
    "triggerNode",
})


def validate_loop_inline_bodies(definition: dict[str, Any]) -> list[str]:
    """Valida estruturalmente todos os ``body`` de loops inline na definition.

    Roda contra ``definition`` antes de publicar uma WorkflowVersion (ou em
    qualquer outro caminho que queira detectar problemas cedo). Retorna
    lista de mensagens de erro — vazia significa OK.

    Verifica:
    - body.nodes nao-vazio.
    - Nenhum tipo proibido (triggers, loop aninhado, workflow_input/output).
    - Nenhum no com mesmo id repetido dentro do body.
    - Edges referenciam apenas ids do proprio body (sem cruzar fronteira).
    - body.nodes nao contem outro nó loop em modo inline (segunda checagem
      explicita; redundante com a regra acima mas com mensagem dedicada).
    """
    errors: list[str] = []
    if not isinstance(definition, dict):
        return errors

    nodes = definition.get("nodes") or []
    if not isinstance(nodes, list):
        return errors

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "?")
        node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
        # ``loop`` no Shift e identificado por ``data.type == 'loop'`` ou
        # pelo campo ``type`` no nivel do node — cobrir ambos.
        is_loop = (
            (node.get("type") or "").lower() == "loop"
            or (node_data.get("type") or "").lower() == "loop"
        )
        if not is_loop:
            continue
        body_mode = str(node_data.get("body_mode") or _BODY_MODE_EXTERNAL).lower()
        if body_mode != _BODY_MODE_INLINE:
            continue
        body = node_data.get("body")
        if not isinstance(body, dict):
            errors.append(
                f"Loop '{node_id}': body inline ausente ou invalido."
            )
            continue
        body_nodes = body.get("nodes") or []
        body_edges = body.get("edges") or []
        if not isinstance(body_nodes, list) or not body_nodes:
            errors.append(
                f"Loop '{node_id}': body.nodes deve ser uma lista nao-vazia."
            )
            continue
        if not isinstance(body_edges, list):
            errors.append(
                f"Loop '{node_id}': body.edges deve ser uma lista."
            )
            body_edges = []

        body_ids: set[str] = set()
        for child in body_nodes:
            if not isinstance(child, dict):
                continue
            child_id = str(child.get("id") or "")
            if not child_id:
                errors.append(
                    f"Loop '{node_id}': no filho sem 'id'."
                )
                continue
            if child_id in body_ids:
                errors.append(
                    f"Loop '{node_id}': id '{child_id}' duplicado no body."
                )
            body_ids.add(child_id)

            child_data = child.get("data") if isinstance(child.get("data"), dict) else {}
            child_type = str(
                child.get("type")
                or child_data.get("type")
                or ""
            ).strip()
            child_data_type = str(child_data.get("type") or "").strip()
            forbidden_hits = (
                {child_type, child_data_type} & _BODY_FORBIDDEN_NODE_TYPES
            )
            if forbidden_hits:
                errors.append(
                    f"Loop '{node_id}': filho '{child_id}' usa tipo proibido em "
                    f"corpo inline: {sorted(forbidden_hits)[0]}."
                )

        for edge in body_edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("source") or "")
            tgt = str(edge.get("target") or "")
            if src and src not in body_ids:
                errors.append(
                    f"Loop '{node_id}': edge referencia source '{src}' fora "
                    "do body inline."
                )
            if tgt and tgt not in body_ids:
                errors.append(
                    f"Loop '{node_id}': edge referencia target '{tgt}' fora "
                    "do body inline."
                )

    return errors


_CHUNK_SIZE = 1000

# Intervalo minimo entre eventos ``node_progress`` para evitar flood de SSE
# quando iteracoes sao muito rapidas (ex.: delete em lote simples). O
# primeiro e o ultimo eventos sempre sao emitidos, independentemente do
# throttle.
_PROGRESS_MIN_INTERVAL_SECONDS = 0.25


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
        source_value = self._resolve_source(node_id, cfg["source_field"], context)
        if source_value is None:
            raise NodeProcessingError(
                f"No loop '{node_id}': source_field nao pode ser resolvido no contexto."
            )

        items = self._materialize_items(node_id, source_value, cfg["max_iterations"])
        if not items:
            return _build_output(cfg, successes=[], failures=[], total=0)

        call_stack = list(context.get("call_stack") or [])
        use_mapping = bool(cfg["input_mapping"])

        # Resolve extra_inputs UMA vez (modo legado — nao depende do item).
        base_inputs: dict[str, Any] = {}
        if not use_mapping:
            for name, path in cfg["extra_inputs"].items():
                if isinstance(path, str):
                    base_inputs[name] = self.resolve_template(path, context)
                else:
                    base_inputs[name] = path

        coro = _run_iterations(
            node_id=node_id,
            cfg=cfg,
            items=items,
            base_inputs=base_inputs,
            call_stack=call_stack,
            processor=self,
            context=context,
        )

        # Mesmo deadline aplicado pelo ``dynamic_runner`` no nivel do no —
        # replicado aqui para podermos cancelar a coroutine interna quando
        # o timeout estoura. Sem isso, o ``asyncio.wait_for`` externo cancela
        # apenas a task ``to_thread`` (que nao consegue matar a thread do
        # worker), enquanto a coroutine ``_run_iterations`` — agendada via
        # ``run_coroutine_threadsafe`` — e uma task independente no main
        # loop e continua rodando por conta propria. Resultado visivel ao
        # usuario: UI mostra "excedeu timeout" mas o backend segue
        # processando iteracoes. Aplicar ``future.result(timeout=...)`` +
        # ``future.cancel()`` fecha essa brecha propagando o cancel para a
        # task real, que por sua vez cancela ``_invoke_subworkflow`` em voo.
        raw_timeout = config.get("timeout_seconds")
        if isinstance(raw_timeout, bool):
            node_timeout = 300.0
        elif isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
            node_timeout = float(raw_timeout)
        else:
            node_timeout = 300.0

        main_loop = context.get("_main_loop")
        if isinstance(main_loop, asyncio.AbstractEventLoop) and main_loop.is_running():
            # Dispatch para o loop principal — recursos async globais
            # (engine/asyncpg) estao ligados a ele. ``asyncio.run`` em
            # outro loop quebra com "Future attached to a different loop".
            future = asyncio.run_coroutine_threadsafe(coro, main_loop)
            try:
                return future.result(timeout=node_timeout)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()  # cancela a Task no main_loop
                raise NodeProcessingError(
                    f"No loop '{node_id}' excedeu timeout de {int(node_timeout)}s "
                    "— iteracoes em voo foram canceladas."
                ) from exc
            except BaseException:
                # Qualquer outra falha (KeyboardInterrupt, cancelamento
                # propagado): garantir que a task nao fique orfa no loop.
                if not future.done():
                    future.cancel()
                raise
        return asyncio.run(coro)

    # ------------------------------------------------------------------
    # Validacao e materializacao do dataset
    # ------------------------------------------------------------------

    def _validate_config(self, node_id: str, config: dict[str, Any]) -> dict[str, Any]:
        raw_mapping = config.get("input_mapping") or {}
        if raw_mapping and not isinstance(raw_mapping, dict):
            raise NodeProcessingError(
                f"No loop '{node_id}': input_mapping deve ser um dict."
            )
        input_mapping: dict[str, Any] = {str(k): v for k, v in raw_mapping.items()}

        body_mode = str(config.get("body_mode") or _BODY_MODE_EXTERNAL).lower()
        if body_mode not in _BODY_MODES:
            raise NodeProcessingError(
                f"No loop '{node_id}': body_mode invalido '{body_mode}'."
            )

        if body_mode == _BODY_MODE_EXTERNAL:
            # Com input_mapping, item_param_name deixa de ser obrigatorio.
            required = ("source_field", "workflow_id")
            if not input_mapping:
                required = required + ("item_param_name",)
            for key in required:
                if not config.get(key):
                    raise NodeProcessingError(
                        f"No loop '{node_id}': '{key}' e obrigatorio."
                    )
            try:
                workflow_id: UUID | None = UUID(str(config["workflow_id"]))
            except (TypeError, ValueError) as exc:
                raise NodeProcessingError(
                    f"No loop '{node_id}': workflow_id invalido."
                ) from exc
            body_payload: dict[str, Any] | None = None
            output_mapping: dict[str, Any] = {}
        else:
            # Modo inline: body obrigatorio, workflow_id ignorado.
            if not config.get("source_field"):
                raise NodeProcessingError(
                    f"No loop '{node_id}': 'source_field' e obrigatorio."
                )
            raw_body = config.get("body")
            if not isinstance(raw_body, dict):
                raise NodeProcessingError(
                    f"No loop '{node_id}': 'body' deve ser um dict {{nodes, edges}} "
                    "no modo inline."
                )
            body_nodes = raw_body.get("nodes") or []
            body_edges = raw_body.get("edges") or []
            if not isinstance(body_nodes, list) or not body_nodes:
                raise NodeProcessingError(
                    f"No loop '{node_id}': 'body.nodes' deve ser uma lista nao-vazia "
                    "no modo inline."
                )
            if not isinstance(body_edges, list):
                raise NodeProcessingError(
                    f"No loop '{node_id}': 'body.edges' deve ser uma lista."
                )
            workflow_id = None
            body_payload = {"nodes": list(body_nodes), "edges": list(body_edges)}

            raw_out = config.get("output_mapping") or {}
            if not isinstance(raw_out, dict):
                raise NodeProcessingError(
                    f"No loop '{node_id}': output_mapping deve ser um dict."
                )
            output_mapping = {str(k): v for k, v in raw_out.items()}

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

        # Nomes das chaves injetadas no input_data do corpo inline.
        item_input_name = str(config.get("iteration_input_name") or "item")
        index_input_name = str(config.get("iteration_index_name") or "idx")

        return {
            "body_mode": body_mode,
            "body": body_payload,
            "output_mapping": output_mapping,
            "iteration_input_name": item_input_name,
            "iteration_index_name": index_input_name,
            "source_field": config["source_field"],
            "workflow_id": workflow_id,
            "workflow_version": config.get("workflow_version", "latest"),
            "item_param_name": (
                str(config["item_param_name"]) if config.get("item_param_name") else None
            ),
            "index_param_name": (
                str(config["index_param_name"]) if config.get("index_param_name") else None
            ),
            "extra_inputs": {str(k): v for k, v in extra.items()},
            "input_mapping": input_mapping,
            "mode": mode,
            "max_parallelism": max_par,
            "on_item_error": on_err,
            "max_iterations": max_iter,
            "output_field": str(config.get("output_field") or "loop_result"),
            "timeout_seconds": int(config.get("timeout_seconds") or 300),
        }

    def _resolve_source(
        self, node_id: str, source_field: Any, context: dict[str, Any]
    ) -> Any:
        from app.services.workflow.parameter_value import (
            ResolutionContext,
            migrate_legacy_loop_source,
            resolve_parameter,
        )

        ctx = ResolutionContext(
            input_data=context.get("input_data") or {},
            upstream_results=context.get("upstream_results") or {},
            vars=context.get("vars") or {},
            all_results=context.get("_all_results") or {},
        )
        pv = migrate_legacy_loop_source(source_field)
        try:
            return resolve_parameter(pv, ctx)
        except (KeyError, ValueError) as exc:
            raise NodeProcessingError(
                f"No loop '{node_id}': nao foi possivel resolver source_field — {exc}"
            ) from exc

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
    # ``read_only=True`` removido — DuckDB nao permite mistura de configs
    # de acesso (read-only vs read-write) ao mesmo arquivo no mesmo
    # processo. Quando um node a jusante (ex: filter) precisava criar
    # tabela RW no mesmo path, batia com:
    # ``ConnectionException: Can't open a connection to same database
    # file with a different configuration than existing connections``.
    # Single-process Shift nao ganha protecao com read_only — default RW
    # le igual sem o conflito.
    conn = duckdb.connect(str(reference["database_path"]))
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
    processor: BaseNodeProcessor,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Roteia para execucao sequencial ou paralela conforme cfg['mode']."""
    results: list[dict[str, Any] | None] = [None] * len(items)
    failures: list[dict[str, Any]] = []
    first_error: Exception | None = None
    use_mapping = bool(cfg["input_mapping"])

    # Progress emission: publica ``node_progress`` com current/total/
    # succeeded/failed para a UI mostrar status ao vivo. Sink e None em
    # cron/agendado — nesse caso as chamadas de emit viram noop.
    event_sink = context.get("_event_sink") if isinstance(context, dict) else None
    execution_id = context.get("_execution_id") if isinstance(context, dict) else None
    total = len(items)
    succeeded_count = 0
    failed_count = 0
    last_emit_mono = 0.0

    async def _emit_progress(force: bool = False) -> None:
        """Envia um evento ``node_progress`` respeitando o throttle.

        Importante: ``force=True`` bypassa o throttle — usado no primeiro
        evento (logo apos materializar o dataset) e no ultimo (apos a
        ultima iteracao) para garantir que a UI nunca perca o inicio nem
        o final.
        """
        nonlocal last_emit_mono
        if event_sink is None:
            return
        now_mono = time.monotonic()
        if not force and (now_mono - last_emit_mono) < _PROGRESS_MIN_INTERVAL_SECONDS:
            return
        last_emit_mono = now_mono
        try:
            await event_sink({
                "type": "node_progress",
                "execution_id": execution_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node_id": node_id,
                "node_type": "loop",
                "current": succeeded_count + failed_count,
                "total": total,
                "succeeded": succeeded_count,
                "failed": failed_count,
            })
        except Exception:  # noqa: BLE001 — progresso nunca deve quebrar o loop
            pass

    async def _run_one(idx: int, item: dict[str, Any]) -> None:
        nonlocal first_error, succeeded_count, failed_count
        if first_error is not None and cfg["on_item_error"] == "fail_fast":
            return
        if use_mapping:
            iter_ctx = {**context, "item": item, "idx": idx}
            inputs: dict[str, Any] = {}
            for name, tmpl in cfg["input_mapping"].items():
                inputs[name] = processor.resolve_data(tmpl, iter_ctx)
        else:
            inputs = dict(base_inputs)
            if cfg["body_mode"] == _BODY_MODE_EXTERNAL:
                # No modo external precisamos respeitar item_param_name/
                # index_param_name (legado). No modo inline o item/idx
                # entram diretamente via _invoke_inline_body.
                inputs[cfg["item_param_name"]] = item
                if cfg["index_param_name"]:
                    inputs[cfg["index_param_name"]] = idx
        try:
            parent_vars = context.get("vars") if isinstance(context, dict) else None
            if cfg["body_mode"] == _BODY_MODE_INLINE:
                iter_output = await _invoke_inline_body(
                    node_id=node_id,
                    body=cfg["body"],
                    item=item,
                    idx=idx,
                    mapped_inputs=inputs,
                    output_mapping=cfg["output_mapping"],
                    iteration_input_name=cfg["iteration_input_name"],
                    iteration_index_name=cfg["iteration_index_name"],
                    parent_context=context,
                    call_stack=call_stack,
                    timeout_seconds=cfg["timeout_seconds"],
                    processor=processor,
                )
                results[idx] = iter_output
            else:
                sub = await _invoke_subworkflow(
                    node_id=node_id,
                    target_workflow_id=cfg["workflow_id"],
                    version_spec=cfg["workflow_version"],
                    mapped_inputs=inputs,
                    parent_vars=dict(parent_vars) if isinstance(parent_vars, dict) else None,
                    call_stack=call_stack,
                    timeout_seconds=cfg["timeout_seconds"],
                    in_loop=True,
                )
                results[idx] = sub["workflow_output"]
            succeeded_count += 1
        except Exception as exc:  # noqa: BLE001 — propagado via politica
            if cfg["on_item_error"] == "fail_fast":
                if first_error is None:
                    first_error = exc
                failed_count += 1
                await _emit_progress(force=True)  # ultima foto antes do abort
                return
            failures.append({
                "index": idx,
                "item": item,
                "error": str(exc),
            })
            failed_count += 1
        await _emit_progress()

    # Evento inicial: avisa a UI que temos N itens, 0 processados.
    await _emit_progress(force=True)

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

    # Evento final: garante que UI veja o estado consolidado mesmo se o
    # throttle tiver suprimido o evento da ultima iteracao.
    await _emit_progress(force=True)

    if first_error is not None:
        raise NodeProcessingError(
            f"No loop '{node_id}': item 0-based abortou o loop (fail_fast) — {first_error}"
        ) from first_error

    successes = [r for r in results if r is not None]
    return _build_output(cfg, successes=successes, failures=failures, total=len(items))


_MAX_INLINE_FAILURES = 20


def _build_output(
    cfg: dict[str, Any],
    *,
    successes: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    total: int,
) -> dict[str, Any]:
    """Monta o dict final conforme a politica de erro.

    Sempre expoe uma amostra de falhas (ate ``_MAX_INLINE_FAILURES``) em
    ``failure_samples`` — mesmo em ``continue`` — para que o usuario veja o
    motivo sem precisar trocar de politica. Em ``collect`` a lista completa
    continua em ``failures``.
    """
    output_field = cfg["output_field"]
    failure_samples = failures[:_MAX_INLINE_FAILURES]
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
            "failure_samples": failure_samples,
        }

    return {
        "status": "completed",
        "iterations": total,
        "successes": len(successes),
        "failures": len(failures),
        "failure_samples": failure_samples,
        "output_field": output_field,
        output_field: payload,
    }


async def _invoke_inline_body(
    *,
    node_id: str,
    body: dict[str, Any],
    item: dict[str, Any],
    idx: int,
    mapped_inputs: dict[str, Any],
    output_mapping: dict[str, Any],
    iteration_input_name: str,
    iteration_index_name: str,
    parent_context: dict[str, Any],
    call_stack: list[str],
    timeout_seconds: int,
    processor: BaseNodeProcessor,
) -> dict[str, Any]:
    """Executa o subgrafo embutido como corpo de uma iteracao.

    Estrategia: reaproveita ``run_workflow`` passando o subgrafo como
    payload arbitrario. Cada iteracao paga seu proprio
    ``execution_id`` (isola arquivos DuckDB) e roda com ``in_loop=True``
    (bloqueia loops aninhados via guard ja existente).

    O ``input_data`` do sub-run carrega ``item`` e ``idx`` em chaves
    configuraveis (``iteration_input_name``/``iteration_index_name``)
    alem de quaisquer ``mapped_inputs`` resolvidos pelo input_mapping.

    Saida da iteracao: combina o ``workflow_output`` acumulado pelos
    nos ``workflow_output`` (se houver) com os campos resolvidos via
    ``output_mapping`` (templates contra os ``upstream_results`` do
    sub-run). ``output_mapping`` tem precedencia em caso de conflito.
    """
    # Lazy import: evita ciclo loop -> dynamic_runner -> processors -> loop.
    from app.orchestration.flows.dynamic_runner import run_workflow

    if not isinstance(body, dict):
        raise NodeProcessingError(
            f"No loop '{node_id}': body inline ausente."
        )

    body_inputs = dict(mapped_inputs)
    body_inputs.setdefault(iteration_input_name, item)
    body_inputs.setdefault(iteration_index_name, idx)

    parent_input_data = parent_context.get("input_data") if isinstance(parent_context, dict) else None
    if isinstance(parent_input_data, dict):
        # Mantem inputs do workflow pai acessiveis (ex.: parametros do
        # call_workflow externo). Item/idx tem precedencia.
        merged = dict(parent_input_data)
        merged.update(body_inputs)
        body_inputs = merged

    parent_vars = parent_context.get("vars") if isinstance(parent_context, dict) else None
    resolved_connections = (
        parent_context.get("_resolved_connections")
        if isinstance(parent_context, dict)
        else None
    )
    workspace_id = parent_context.get("workspace_id") if isinstance(parent_context, dict) else None
    parent_mode = parent_context.get("mode") if isinstance(parent_context, dict) else "production"

    sub_execution_id = f"loop-inline-{node_id}-{idx}-{uuid4()}"

    try:
        sub_result = await asyncio.wait_for(
            run_workflow(
                workflow_payload={
                    "nodes": body.get("nodes", []),
                    "edges": body.get("edges", []),
                },
                # NAO passar workflow_id: evita ciclo "self-call" no guard
                # de call_stack (o subgrafo NAO e outro workflow, e parte
                # deste mesmo run logico).
                workflow_id=None,
                triggered_by="loop_inline",
                input_data=body_inputs,
                execution_id=sub_execution_id,
                resolved_connections=dict(resolved_connections) if isinstance(resolved_connections, dict) else None,
                variable_values=dict(parent_vars) if isinstance(parent_vars, dict) else None,
                mode=parent_mode if isinstance(parent_mode, str) else "production",
                call_stack=call_stack,
                in_loop=True,
                workspace_id=workspace_id if isinstance(workspace_id, str) else None,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise NodeProcessingError(
            f"No loop '{node_id}' (inline, idx={idx}): corpo excedeu "
            f"{timeout_seconds}s."
        ) from exc

    status = sub_result.get("status")
    if status != "completed":
        raise NodeProcessingError(
            f"No loop '{node_id}' (inline, idx={idx}): corpo retornou status "
            f"'{status}': {sub_result.get('error') or sub_result.get('reason') or ''}"
        )

    iteration_output: dict[str, Any] = {}
    accumulated = sub_result.get("workflow_output")
    if isinstance(accumulated, dict):
        iteration_output.update(accumulated)

    if output_mapping:
        # Resolve templates contra os resultados internos do sub-run +
        # item/idx, permitindo capturar campos sem precisar de um no
        # ``workflow_output`` no body.
        resolve_ctx = {
            "input_data": body_inputs,
            "upstream_results": sub_result.get("node_results") or {},
            "_all_results": sub_result.get("node_results") or {},
            "item": item,
            "idx": idx,
            "vars": parent_vars if isinstance(parent_vars, dict) else {},
        }
        for name, tmpl in output_mapping.items():
            iteration_output[name] = processor.resolve_data(tmpl, resolve_ctx)

    return iteration_output
