"""
Orquestrador dinamico de workflows.

Recebe o payload do React Flow (nodes + edges), constroi a ordem de
execucao via ordenacao topologica e despacha as coroutines
correspondentes a cada tipo de no.

Cada no e executado individualmente pelo registry de processors.
Nos de transformacao (math, filter, mapper, aggregator) materializam
seus resultados em DuckDB, que e passado adiante como referencia.
O no de carga (loadNode) le o DuckDB e escreve no destino final via dlt.

Emissao de eventos (opcional)
-----------------------------
``run_workflow`` aceita um ``event_sink: Callable[[dict], Awaitable[None]]``
opcional para observabilidade em tempo real. Quando fornecido, o runner
emite eventos de ciclo de vida (execution_start, node_start, node_complete,
node_error, node_error_handled, node_skipped, execution_end) para o sink —
usado pelo ``workflow_test_service`` para transformar em SSE. Quando
``None`` (padrao em execucoes cron), nao ha overhead.

Excecoes do sink NAO derrubam a execucao: sao capturadas e logadas
como warning.

Flags por no (``data.pinnedOutput``, ``data.enabled``)
------------------------------------------------------
Dois flags sao avaliados ANTES de despachar cada no:

- ``pinnedOutput``: quando ``data.pinnedOutput`` e um dict truthy, seu
  conteudo vira diretamente o resultado do no (passthrough) — o processor
  NAO e chamado. O evento ``node_complete`` inclui ``is_pinned=True`` e
  o ``WorkflowNodeExecution`` e gravado como ``status="skipped"``
  com ``output_summary={"is_pinned": True}``. Downstream recebe o
  pinnedOutput como se fosse saida real.

- ``enabled is False``: o no e pulado e propaga skip em cascata para
  os descendentes (mesma mecanica de ``skipped_by_branch``). Emite
  ``node_skipped`` com ``reason="disabled"``.

Ramificacao condicional
-----------------------
Nos de condicao (ifElse, switch, if_node, switch_node) retornam um marcador
de handles ativos em seu resultado, que o runner usa para decidir quais
arestas de saida sao ativadas:

- ``active_handle`` (string, semantica all-or-nothing): apenas o handle
  informado e ativo; os demais sao desativados. Usado por ``ifElse`` e
  ``switch`` (apenas um ramo do grafo e executado).
- ``active_handles`` (list[str], semantica row-partition): cada handle listado
  e ativo. Usado por ``if_node`` e ``switch_node`` quando o no particiona
  linhas por ramo — ambos os ramos podem rodar em paralelo com seus
  subconjuntos de linhas.

Em ambos os casos, arestas cujo ``sourceHandle`` nao esta no conjunto ativo
sao adicionadas a ``inactive_edges``. Nos cujas TODAS as entradas estao em
``inactive_edges`` ou em ``skipped_nodes`` sao marcados com
``status: "skipped_by_branch"`` e nao sao executados. Esse estado se propaga
em cascata para os descendentes. Nos de juncao com ao menos uma entrada
ativa sao executados normalmente, recebendo apenas os resultados upstream
ativos no contexto.

Roteamento de ``branches`` (row-partition)
------------------------------------------
Nos row-partition retornam ``branches``: ``{handle_id -> DuckDbReference}``,
onde cada referencia aponta para a tabela DuckDB que contem apenas as
linhas daquele ramo. Ao construir o ``upstream_results`` de um no a jusante,
o runner identifica o ``sourceHandle`` da aresta origem->destino e substitui
a referencia primaria do resultado upstream pela particao correspondente
(ver ``_route_upstream_result``). Assim ``get_primary_input_reference``
retorna automaticamente a tabela correta para o ramo conectado.
"""

import asyncio
import os
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import bind_context, get_logger
from app.core.observability import (
    record_execution,
    record_node,
    start_execution_span,
    start_node_span,
)
from app.db.session import async_session_factory
from app.models.workflow import Workflow
from app.orchestration.tasks.llm_task import execute_llm_node
from app.orchestration.tasks.node_processor import execute_registered_node
from app.services.workflow.nodes import has_processor
from app.services.workflow.nodes.exceptions import (
    NodeProcessingError,
    NodeProcessingSkipped,
)


EventSink = Callable[[dict[str, Any]], Awaitable[None]]


DEFAULT_NODE_TIMEOUT_SECONDS = 300

# ---------------------------------------------------------------------------
# Controle de concorrencia de execucoes
# ---------------------------------------------------------------------------

_MAX_CONCURRENT_EXECUTIONS = int(os.getenv("SHIFT_MAX_CONCURRENT_EXECUTIONS", "10"))
_MAX_CONCURRENT_PER_PROJECT = int(os.getenv("SHIFT_MAX_CONCURRENT_PER_PROJECT", "3"))
_EXECUTION_QUEUE_TIMEOUT = float(os.getenv("SHIFT_EXECUTION_QUEUE_TIMEOUT", "60"))


def _check_disk_limit() -> None:
    """Levanta ``ConcurrencyLimitError`` se o diretorio /tmp/shift superar o limite."""
    from app.core.config import settings  # import tardio para evitar ciclo  # noqa: PLC0415

    max_gb = settings.SHIFT_MAX_DISK_GB
    if max_gb <= 0:
        return
    base = Path(tempfile.gettempdir()) / "shift"
    if not base.exists():
        return
    total_bytes = sum(
        f.stat().st_size
        for f in base.rglob("*")
        if f.is_file()
    )
    used_gb = total_bytes / (1024 ** 3)
    if used_gb >= max_gb:
        raise ConcurrencyLimitError(
            f"Espaco em disco insuficiente: /tmp/shift usa {used_gb:.1f} GB "
            f"(limite: {max_gb} GB). Aguarde a conclusao de execucoes ativas."
        )

# Semaforo global: limite total de execucoes simultaneas nesta instancia.
_global_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_EXECUTIONS)
# Semaforos por projeto: criados sob demanda, protegidos por lock.
_project_semaphores: dict[str, asyncio.Semaphore] = {}
_project_semaphores_lock = asyncio.Lock()

# Contadores de monitoramento (sem lock — leitura aproximada e suficiente).
_active_count: int = 0
_queued_count: int = 0
_active_by_project: dict[str, int] = defaultdict(int)


class ConcurrencyLimitError(Exception):
    """Levantada quando o limite de concorrencia e atingido apos timeout."""


async def _get_project_semaphore(project_id: str) -> asyncio.Semaphore:
    async with _project_semaphores_lock:
        if project_id not in _project_semaphores:
            _project_semaphores[project_id] = asyncio.Semaphore(
                _MAX_CONCURRENT_PER_PROJECT
            )
        return _project_semaphores[project_id]


async def acquire_execution_slot(project_id: str | None = None) -> None:
    """Adquire slot global e por-projeto com timeout de ``_EXECUTION_QUEUE_TIMEOUT`` s.

    Levanta ``ConcurrencyLimitError`` se nenhum slot liberar dentro do timeout
    ou se o limite de disco estiver excedido.
    """
    global _active_count, _queued_count  # noqa: PLW0603

    # Import tardio — keep concurrency module independente da observabilidade
    # em testes que mockam apenas estes simbolos.
    from app.core.observability.metrics import (  # noqa: PLC0415
        SPAWNER_ACTIVE,
        SPAWNER_ERRORS_TOTAL,
        SPAWNER_SPAWNED_TOTAL,
    )

    _check_disk_limit()
    _queued_count += 1
    try:
        try:
            await asyncio.wait_for(
                _global_semaphore.acquire(), timeout=_EXECUTION_QUEUE_TIMEOUT
            )
        except asyncio.TimeoutError:
            SPAWNER_ERRORS_TOTAL.labels("execution", "ConcurrencyLimitError").inc()
            raise ConcurrencyLimitError(
                f"Limite global de execucoes concorrentes atingido "
                f"({_MAX_CONCURRENT_EXECUTIONS} ativas). "
                "Tente novamente em alguns instantes."
            ) from None

        if project_id:
            sem = await _get_project_semaphore(project_id)
            try:
                await asyncio.wait_for(
                    sem.acquire(), timeout=_EXECUTION_QUEUE_TIMEOUT
                )
            except asyncio.TimeoutError:
                _global_semaphore.release()
                SPAWNER_ERRORS_TOTAL.labels(
                    "project_slot", "ConcurrencyLimitError"
                ).inc()
                raise ConcurrencyLimitError(
                    f"Limite de execucoes concorrentes por projeto atingido "
                    f"({_MAX_CONCURRENT_PER_PROJECT} ativas neste projeto). "
                    "Tente novamente em alguns instantes."
                ) from None
    finally:
        _queued_count = max(0, _queued_count - 1)

    _active_count += 1
    if project_id:
        _active_by_project[project_id] += 1
    SPAWNER_ACTIVE.labels("execution").set(_active_count)
    SPAWNER_SPAWNED_TOTAL.labels("execution").inc()
    if project_id:
        SPAWNER_ACTIVE.labels("project_slot").set(
            sum(_active_by_project.values())
        )
        SPAWNER_SPAWNED_TOTAL.labels("project_slot").inc()


def release_execution_slot(project_id: str | None = None) -> None:
    """Libera slot global e por-projeto adquiridos em ``acquire_execution_slot``."""
    global _active_count  # noqa: PLW0603

    from app.core.observability.metrics import SPAWNER_ACTIVE  # noqa: PLC0415

    _global_semaphore.release()
    if project_id and project_id in _project_semaphores:
        _project_semaphores[project_id].release()
        _active_by_project[project_id] = max(
            0, _active_by_project.get(project_id, 0) - 1
        )
    _active_count = max(0, _active_count - 1)
    SPAWNER_ACTIVE.labels("execution").set(_active_count)
    if project_id:
        SPAWNER_ACTIVE.labels("project_slot").set(
            sum(_active_by_project.values())
        )


def get_concurrency_metrics() -> dict[str, Any]:
    """Retorna metricas de concorrencia para o endpoint de saude."""
    return {
        "active_executions": _active_count,
        "queued_executions": _queued_count,
        "max_concurrent": _MAX_CONCURRENT_EXECUTIONS,
        "max_per_project": _MAX_CONCURRENT_PER_PROJECT,
        "active_by_project": dict(_active_by_project),
    }

# --- Sub-workflows -----------------------------------------------------
# Profundidade maxima de chamadas aninhadas via ``call_workflow``. O
# contador e baseado em workflow_id (nao no_id), entao inclui o pai na
# contagem. Default 5 (= pai + 4 niveis de sub).
SUBWORKFLOW_MAX_DEPTH = 5


class SubWorkflowCycleError(Exception):
    """Levantada quando ``call_workflow`` forma um ciclo entre workflows."""


class SubWorkflowDepthError(Exception):
    """Levantada quando ``call_workflow`` ultrapassa SUBWORKFLOW_MAX_DEPTH."""



def _resolve_node_timeout(node_data: dict[str, Any]) -> float:
    """Extrai ``timeout_seconds`` do config, com fallback para o default.

    Aceita int ou float positivo; qualquer outro valor cai no default.
    """
    raw = node_data.get("timeout_seconds")
    if isinstance(raw, bool):  # bool e subclasse de int — descartar
        return DEFAULT_NODE_TIMEOUT_SECONDS
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return DEFAULT_NODE_TIMEOUT_SECONDS


async def _run_with_timeout(
    node_id: str,
    coro: Any,
    timeout: float,
    logger: Any,
) -> dict[str, Any]:
    """Aplica ``asyncio.wait_for`` e converte TimeoutError em NodeProcessingError."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as exc:
        logger.error("node.timeout", node_id=node_id, timeout=timeout)
        raise NodeProcessingError(
            f"No '{node_id}' excedeu timeout de {timeout}s"
        ) from exc


def _parse_retry_policy(raw: Any) -> "RetryPolicyConfig | None":
    """Valida ``retry_policy`` do config como ``RetryPolicyConfig``.

    Aceita dict ou instancia pronta; qualquer coisa invalida vira ``None``
    — ausencia de politica = execucao de tentativa unica (backward compat).
    """
    from app.schemas.workflow import RetryPolicyConfig

    if raw is None:
        return None
    if isinstance(raw, RetryPolicyConfig):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return RetryPolicyConfig.model_validate(raw)
    except Exception:  # noqa: BLE001 — politicas invalidas sao silenciosamente ignoradas
        return None


def _compute_backoff(policy: "RetryPolicyConfig", attempt: int) -> float:
    """Calcula o atraso entre duas tentativas (apos a ``attempt``-esima falhar)."""
    if policy.backoff_strategy == "none":
        return 0.0
    if policy.backoff_strategy == "fixed":
        return float(policy.backoff_seconds)
    # exponential: base * 2^(attempt-1)
    return float(policy.backoff_seconds) * (2 ** (attempt - 1))


async def _run_with_retry(
    *,
    node_id: str,
    attempt_factory: Callable[[], Awaitable[dict[str, Any]]],
    policy: "RetryPolicyConfig | None",
    timeout: float,
    logger: Any,
    event_sink: EventSink | None,
    execution_id: str | None,
    node_type_for_event: str,
    label_for_event: str,
) -> dict[str, Any]:
    """Executa ``attempt_factory`` com retry conforme ``policy``.

    Cada tentativa recebe uma coroutine fresca via ``attempt_factory()`` —
    re-usar a mesma coroutine e erro em asyncio. Retry so dispara para
    ``NodeProcessingError``; outras excecoes propagam imediatamente.
    Ausencia de politica = tentativa unica (comportamento original).
    """
    attempts = policy.max_attempts if policy else 1
    last_exc: NodeProcessingError | None = None
    for attempt in range(1, attempts + 1):
        try:
            # Span por TENTATIVA — uma falha + retry resulta em dois spans
            # filhos do span de execucao, com o atributo ``attempt`` para
            # diferenciar. Em ferramentas como Jaeger isso aparece como
            # uma timeline visual de "tentou, falhou, esperou X, tentou de novo".
            with start_node_span(
                node_id=node_id,
                node_type=node_type_for_event,
                execution_id=execution_id,
            ) as _span:
                if attempts > 1:
                    try:
                        _span.set_attribute("attempt", str(attempt))
                        _span.set_attribute("max_attempts", str(attempts))
                    except Exception:  # noqa: BLE001
                        pass
                return await _run_with_timeout(
                    node_id=node_id,
                    coro=attempt_factory(),
                    timeout=timeout,
                    logger=logger,
                )
        except NodeProcessingError as exc:
            last_exc = exc
            msg = str(exc)
            if policy is None or attempt >= attempts:
                raise
            if policy.retry_on and not any(s in msg for s in policy.retry_on):
                # erro nao bate o filtro de substrings — desiste sem retry
                raise
            delay = _compute_backoff(policy, attempt)
            await _safe_emit(
                event_sink,
                {
                    "type": "node_retry",
                    "execution_id": execution_id,
                    "timestamp": _iso_now(),
                    "node_id": node_id,
                    "node_type": node_type_for_event,
                    "label": label_for_event,
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "next_delay_seconds": delay,
                    "error": msg,
                },
                logger,
            )
            if delay > 0:
                await asyncio.sleep(delay)
    # Defensivo: loop saiu sem return nem raise (nao deveria acontecer).
    if last_exc is not None:
        raise last_exc
    raise NodeProcessingError(f"No '{node_id}': retry policy exausto sem erro registrado")


async def _load_workflow_payload_from_db(workflow_id: UUID) -> dict[str, Any]:
    """Carrega a definicao do workflow do banco para execucoes agendadas."""
    async with async_session_factory() as session:  # type: AsyncSession
        result = await session.execute(
            select(Workflow.definition).where(Workflow.id == workflow_id)
        )
        workflow_definition = result.scalar_one_or_none()

    if workflow_definition is None:
        raise ValueError(f"Workflow '{workflow_id}' nao encontrado.")

    return dict(workflow_definition)


def _build_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, int],
    dict[str, dict[str, Any]],
    dict[tuple[str, str], str | None],
    dict[tuple[str, str], str | None],
]:
    """Constroi o grafo direcionado a partir de nos e arestas.

    Alem das estruturas de adjacencia e grau, retorna:
    - ``edge_handle_map``: ``(source, target) -> sourceHandle | None`` — porta de saida ativa.
    - ``target_handle_map``: ``(source, target) -> targetHandle | None`` — porta de entrada no
      no destino. Usado por nos com multiplas entradas (join, lookup) para identificar qual
      upstream chegou em qual handle (ex: ``"left"``, ``"right"``).
    """
    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse_adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {}
    node_map: dict[str, dict[str, Any]] = {}
    edge_handle_map: dict[tuple[str, str], str | None] = {}
    target_handle_map: dict[tuple[str, str], str | None] = {}

    for node in nodes:
        node_id = str(node["id"])
        node_map[node_id] = node
        in_degree[node_id] = 0

    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        # React Flow usa camelCase; suportamos tambem snake_case.
        source_handle: str | None = (
            edge.get("sourceHandle") or edge.get("source_handle") or None
        )
        target_handle: str | None = (
            edge.get("targetHandle") or edge.get("target_handle") or None
        )
        adjacency[source].append(target)
        reverse_adj[target].append(source)
        in_degree[target] = in_degree.get(target, 0) + 1
        edge_handle_map[(source, target)] = source_handle
        target_handle_map[(source, target)] = target_handle

    return adjacency, reverse_adj, in_degree, node_map, edge_handle_map, target_handle_map


def _is_node_skipped(
    node_id: str,
    reverse_adj: dict[str, list[str]],
    skipped_nodes: set[str],
    inactive_edges: set[tuple[str, str]],
) -> bool:
    """Verifica se um no deve ser ignorado por ramificacao condicional.

    Um no e ignorado quando TODAS as suas arestas de entrada sao inativas,
    seja porque o no de origem foi ignorado (``skipped_nodes``) ou porque a
    aresta vem de um handle que nao foi ativado (``inactive_edges``).

    Nos de juncao com ao menos uma entrada ativa sao executados normalmente.
    Nos raiz (sem predecessores) nunca sao ignorados por esta regra.
    """
    sources = reverse_adj.get(node_id, [])
    if not sources:
        return False  # no raiz: nenhuma dependencia, sempre executa

    for source_id in sources:
        if source_id not in skipped_nodes and (source_id, node_id) not in inactive_edges:
            return False  # encontrou ao menos uma entrada ativa

    # Todas as entradas sao inativas ou de nos ignorados.
    return True


def _topological_sort_levels(
    in_degree: dict[str, int],
    adjacency: dict[str, list[str]],
) -> list[list[str]]:
    """
    Ordenacao topologica por niveis (BFS / Kahn).
    Cada nivel contem nos que podem rodar em paralelo.
    """
    queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
    levels: list[list[str]] = []

    while queue:
        current_level = list(queue)
        queue.clear()

        for node_id in current_level:
            for neighbor in adjacency.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        levels.append(current_level)

    return levels


def _inject_connection_string(
    config: dict[str, Any],
    resolved_connections: dict[str, str],
) -> dict[str, Any]:
    """
    Substitui ``connection_id`` por ``connection_string`` no config do no.

    Se o config nao contiver ``connection_id``, retorna o config original sem copia.
    Se contiver, retorna um novo dict com ``connection_string`` injetado, mantendo
    todos os outros campos — inclusive o ``connection_id`` original, caso o processador
    precise dele para fins de log ou auditoria.

    Levanta NodeProcessingError se o ID nao estiver em ``resolved_connections``,
    o que indica que a resolucao pre-execucao falhou ou o ID e invalido.
    """
    conn_id = config.get("connection_id")
    if conn_id is None:
        return config

    conn_id_str = str(conn_id)
    conn_str = resolved_connections.get(conn_id_str)
    if conn_str is None:
        raise NodeProcessingError(
            f"connection_id '{conn_id_str}' nao encontrado nas conexoes resolvidas. "
            "Verifique se o conector esta configurado corretamente no workspace."
        )
    return {**config, "connection_string": conn_str}


def _get_node_type(node: dict[str, Any]) -> str:
    """Extrai o tipo do no de forma segura."""
    return str(node.get("type") or node.get("data", {}).get("type", "unknown"))


def _derive_node_status(result: Any) -> tuple[str, int | None]:
    """Deriva ``(status_sse, failed_count)`` a partir do resultado do no.

    Resolve o problema do runner hardcodar ``"success"`` mesmo quando o
    processor reportou erro/rejeicao por linha. Cobre os casos:
    - bulk_insert/loadNode com ``rejected_count`` > 0 e ``rows_written`` > 0
      -> ``partial`` (amarelo/aviso na UI)
    - bulk_insert com 100% de linhas falhando -> ``error`` (vermelho)
    - resultado com ``status`` explicito (ex.: "skipped", "error") -> propaga
    - default -> ``success``
    """
    if not isinstance(result, dict):
        return "success", None

    explicit = result.get("status")
    if isinstance(explicit, str) and explicit in {"error", "partial", "skipped"}:
        failed = result.get("failed_rows_count") or result.get("rejected_count")
        return explicit, int(failed) if isinstance(failed, int) else None

    failed_raw = result.get("failed_rows_count") or result.get("rejected_count")
    failed = int(failed_raw) if isinstance(failed_raw, int) and failed_raw > 0 else None
    rows_written = result.get("rows_written")
    rows_written_int = int(rows_written) if isinstance(rows_written, int) else None

    if failed:
        if rows_written_int is None or rows_written_int == 0:
            return "error", failed
        return "partial", failed

    return "success", None


def _extract_error_summary(result: Any, status: str, failed_count: int | None) -> str | None:
    """Extrai uma mensagem de erro humana a partir do result quando o status
    e error/partial — corrige o bug em que o OutputPanel renderizava ``ERRO``
    sem texto algum (rejeicao interna por linha sem exception no nó).

    Estrategia:
    1) Se result.error existe (campo explicito), usa.
    2) Se ha rejected_rows, monta resumo: "<N linhas rejeitadas> | <primeira mensagem>"
    3) Se nada bater, mensagem generica orientando a olhar o branch on_error.
    """
    if status not in {"error", "partial"}:
        return None
    if not isinstance(result, dict):
        return None

    if isinstance(result.get("error"), str) and result["error"].strip():
        return result["error"][:600]

    rejected = result.get("rejected_rows")
    if isinstance(rejected, list) and rejected:
        first = rejected[0] if isinstance(rejected[0], dict) else {}
        first_msg = str(first.get("error") or "").strip()
        if first_msg:
            n = failed_count or len(rejected)
            return f"{n} linha(s) rejeitada(s). Primeiro erro: {first_msg[:400]}"

    if failed_count:
        return (
            f"{failed_count} linha(s) rejeitada(s). Verifique o branch "
            "'on_error' para diagnostico por linha."
        )
    return None


def _extract_row_counts(result: Any) -> tuple[int | None, int | None]:
    """Deriva ``(row_count_in, row_count_out)`` a partir do resultado do no.

    Reconhece chaves comuns usadas pelos processors e pelo load_service.
    Segue as mesmas heuristicas do ``workflow_test_service`` para manter
    consistencia das metricas persistidas.
    """
    if not isinstance(result, dict):
        return None, None

    def _as_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    # Entrada: total_input (mapper/filter) tem prioridade; depois row_count bruto.
    row_in = _as_int(result.get("total_input")) or _as_int(result.get("row_count"))

    # Saida: rows_written (loadNode/bulk_insert) tem prioridade; depois row_count.
    row_out = _as_int(result.get("rows_written")) or _as_int(result.get("row_count"))

    # Row-partition (if_node/switch_node): total de saida = soma dos buckets.
    if "true_count" in result or "false_count" in result:
        true_c = _as_int(result.get("true_count")) or 0
        false_c = _as_int(result.get("false_count")) or 0
        if row_out is None:
            row_out = true_c + false_c

    return row_in, row_out


# Chaves que nao devem ser copiadas para o output_summary persistido em DB
# (seja por tamanho, seja por conterem estruturas nao serializaveis ou credenciais).
_OUTPUT_SUMMARY_DROP_KEYS = frozenset({"rows", "data", "upstream_results", "connection_string"})

# Chaves de credencial/segredo que nunca devem sair no payload SSE, mesmo
# que a UI precise de ``data``/``rows`` para preview. Lista mais restrita
# que ``_OUTPUT_SUMMARY_DROP_KEYS`` de proposito — o SSE mantem o shape
# completo do result para renderizar previews; apenas removemos segredos.
_EVENT_OUTPUT_DROP_KEYS = frozenset({
    "connection_string",
    "password",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
})


def _sanitize_for_event(value: Any) -> Any:
    """Remove chaves sensiveis recursivamente antes de emitir em SSE.

    Mantem estruturas como ``data`` (referencia DuckDB) e ``rows`` (preview)
    intactas — a UI precisa delas. So dropa chaves que casam com segredos
    conhecidos. Aplica-se em qualquer profundidade, inclusive dentro de
    ``upstream_results`` ou ``branches``.
    """
    if isinstance(value, dict):
        return {
            k: _sanitize_for_event(v)
            for k, v in value.items()
            if k not in _EVENT_OUTPUT_DROP_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_for_event(item) for item in value]
    return value


def _summarize_result(result: Any) -> dict[str, Any]:
    """Constroi um resumo seguro para JSONB descartando payloads pesados.

    Remove arrays ``rows`` e a referencia DuckDB primaria em ``data`` — essas
    estruturas podem ter milhares de linhas ou paths efemeros que nao fazem
    sentido gravar no snapshot de auditoria.
    """
    if not isinstance(result, dict):
        return {"value": str(result)[:500]}

    summary: dict[str, Any] = {}
    for key, value in result.items():
        if key in _OUTPUT_SUMMARY_DROP_KEYS:
            continue
        if isinstance(value, dict):
            # Remove array de linhas aninhado caso exista
            summary[key] = {k: v for k, v in value.items() if k != "rows"}
        elif isinstance(value, list) and len(value) > 20:
            summary[key] = {"_truncated": True, "length": len(value)}
        else:
            summary[key] = value
    return summary


def _route_upstream_result(
    source_result: dict[str, Any],
    source_handle: str | None,
) -> dict[str, Any]:
    """
    Seleciona a particao correta quando o no upstream e row-partition.

    Nos row-partition retornam ``branches``: ``{handle_id -> DuckDbReference}``.
    Para rotear o downstream para o ramo correto, substituimos a referencia
    primaria no resultado com a particao que corresponde ao ``sourceHandle``
    da aresta.

    O shape retornado usa ``output_field="data"`` apontando para a referencia
    especifica do ramo — ``find_duckdb_reference`` encontra essa referencia
    primeiro (via resolucao de ``output_field``) e ignora o dicionario
    ``branches`` original.

    Quando o no upstream nao e row-partition (sem ``branches``), ou quando a
    aresta nao tem ``sourceHandle``, retorna o resultado intacto.
    """
    if not isinstance(source_result, dict):
        return source_result

    branches = source_result.get("branches")
    if not isinstance(branches, dict) or source_handle is None:
        return source_result

    branch_ref = branches.get(source_handle)
    if not isinstance(branch_ref, dict):
        return source_result

    return {
        **source_result,
        "output_field": "data",
        "data": branch_ref,
    }


def _get_registered_processor_type(node: dict[str, Any]) -> str | None:
    """Normaliza o tipo do no para o registry de processors."""
    node_type = _get_node_type(node)
    node_data = node.get("data", {})
    data_type = str(node_data.get("type", ""))

    if node_type == "triggerNode":
        legacy_type = str(node_data.get("trigger_type", "manual"))
        normalized_type = "cron" if legacy_type == "schedule" else legacy_type
        return normalized_type if has_processor(normalized_type) else None

    if has_processor(node_type):
        return node_type

    if has_processor(data_type):
        return data_type

    return None


async def _resolve_workflow_payload(
    workflow_payload: dict[str, Any] | None,
    workflow_id: str | None,
) -> dict[str, Any]:
    """Resolve o payload do workflow, carregando-o do banco quando necessario."""
    if workflow_payload is not None:
        return workflow_payload

    if workflow_id is None:
        raise ValueError(
            "workflow_payload ou workflow_id deve ser informado para executar o workflow."
        )

    return await _load_workflow_payload_from_db(UUID(workflow_id))


def _filter_payload_to_ancestors(
    definition: dict[str, Any],
    target_node_id: str | None,
) -> dict[str, Any]:
    """Reduz o payload aos ancestrais (inclusive) de ``target_node_id``.

    Usado pelo botao "testar ate aqui" do frontend: quando o usuario quer
    executar apenas uma parcela do grafo que termina em um no especifico,
    recortamos antes de construir o grafo para que o runner nao veja nos
    a jusante do alvo.

    Se ``target_node_id`` e None ou nao existe no payload, retorna o
    original sem copia.
    """
    if not target_node_id:
        return definition

    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    node_ids = {str(n["id"]) for n in nodes if "id" in n}
    if target_node_id not in node_ids:
        return definition

    required: set[str] = {target_node_id}
    stack = [target_node_id]
    while stack:
        current = stack.pop()
        for edge in edges:
            if str(edge.get("target")) == current:
                src = str(edge.get("source"))
                if src in node_ids and src not in required:
                    required.add(src)
                    stack.append(src)

    filtered_nodes = [n for n in nodes if str(n.get("id")) in required]
    filtered_edges = [
        e for e in edges
        if str(e.get("source")) in required and str(e.get("target")) in required
    ]
    return {**definition, "nodes": filtered_nodes, "edges": filtered_edges}


async def _safe_emit(
    event_sink: EventSink | None,
    event: dict[str, Any],
    logger: Any,
) -> None:
    """Chama o event_sink protegido por try/except.

    O sink e observabilidade — exceptions dele NAO devem derrubar a
    execucao do workflow. Apenas logamos warning.
    """
    if event_sink is None:
        return
    try:
        await event_sink(event)
    except Exception as exc:  # noqa: BLE001 — sink e codigo externo
        logger.warning("event_sink.failed", error=f"{type(exc).__name__}: {exc}")


def _event_node_meta(node: dict[str, Any]) -> tuple[str, str | None]:
    """Extrai ``(node_type, label)`` usados nos payloads de evento."""
    node_type = _get_node_type(node)
    node_data = node.get("data", {}) if isinstance(node, dict) else {}
    label = node_data.get("label") if isinstance(node_data, dict) else None
    label_str = str(label)[:255] if label is not None else None
    return node_type, label_str


def _extract_pinned_output(pinned: dict[str, Any]) -> dict[str, Any]:
    """Extrai o resultado real de um pinnedOutput em qualquer formato de versão.

    - **v3** (linhas materializadas): reconstrói ``{rows, columns, row_count}``.
    - **v2** (referência DuckDB ephemeral): retorna o campo ``output`` se
      disponível; caso contrário devolve um dict vazio (referência expirou).
    - **v1 / legado**: devolve o dict puro sem modificação.

    O resultado é passado para ``_default_success_handle_if_needed`` e depois
    para ``results[node_id]``, onde os processadores downstream o leem via
    ``get_primary_input_reference`` ou pelo dict direto (nos legado/inline).
    """
    version = pinned.get("__pinned_v")
    if version == 3:
        return {
            "rows": pinned.get("rows", []),
            "columns": pinned.get("columns", []),
            "row_count": pinned.get("row_count", 0),
        }
    if version == 2:
        output = pinned.get("output")
        if isinstance(output, dict):
            return output
        # Referência-only: DuckDB pode ter expirado — retorna vazio.
        return {"rows": [], "columns": [], "row_count": 0}
    # v1 legado: o próprio dict é o resultado.
    return pinned


def _default_success_handle_if_needed(
    node_id: str,
    result: dict[str, Any],
    adjacency: dict[str, list[str]],
    edge_handle_map: dict[tuple[str, str], str | None],
) -> dict[str, Any]:
    """Defaulta ``active_handle='success'`` para nos com branch de erro.

    O fallback so se aplica quando o resultado NAO declarou
    ``active_handle``/``active_handles`` e quando existe ao menos uma
    aresta de saida marcada como ``success`` ou ``on_error``. Isso evita
    quebrar nos de decisao (``if_node``, ``switch_node``) e preserva
    backward compat para workflows antigos cujas arestas nao tinham
    ``sourceHandle``.
    """
    if not isinstance(result, dict):
        return result

    active_handle = result.get("active_handle")
    if active_handle is not None:
        return result

    active_handles = result.get("active_handles")
    if isinstance(active_handles, (list, tuple, set)):
        return result

    if isinstance(result.get("branches"), dict):
        return result

    outgoing_handles = {
        edge_handle_map.get((node_id, target_id))
        for target_id in adjacency.get(node_id, [])
    }
    if not any(handle in {"success", "on_error"} for handle in outgoing_handles):
        return result

    return {
        **result,
        "active_handle": "success",
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _describe_duckdb_table(ref: dict | None) -> list[tuple[str, str]] | None:
    """Returns ``[(col_name, col_type), ...]`` para a tabela DuckDB referenciada,
    ou ``None`` se nao aplicavel/erro. Centraliza o DESCRIBE para reuso em
    fingerprint e em extracao de colunas."""
    if not ref or ref.get("storage_type") != "duckdb":
        return None
    try:
        import duckdb as _duckdb  # noqa: PLC0415
        from app.data_pipelines.duckdb_storage import build_table_ref  # noqa: PLC0415

        con = _duckdb.connect(str(ref["database_path"]))
        try:
            table_ref = build_table_ref(ref)
            return [(str(c[0]), str(c[1])) for c in con.execute(f"DESCRIBE {table_ref}").fetchall()]
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None


def _compute_schema_fingerprint(ref: dict | None) -> str | None:
    """Computes a short hash of the DuckDB table schema for change detection.

    Called synchronously after node completion — DuckDB DESCRIBE on a local
    file is O(1) metadata read, typically < 1ms.
    """
    cols = _describe_duckdb_table(ref)
    if cols is None:
        return None
    try:
        import hashlib  # noqa: PLC0415
        schema_str = ",".join(f"{c[0]}:{c[1]}" for c in cols)
        return hashlib.md5(schema_str.encode()).hexdigest()[:16]  # noqa: S324
    except Exception:  # noqa: BLE001
        return None


def _extract_output_columns(ref: dict | None) -> list[str] | None:
    """Retorna a lista de nomes de colunas da tabela DuckDB upstream — usada
    no SSE node_complete pra alimentar pickers/auto-map dos nos downstream
    sem precisar bater na API de preview por upstream."""
    cols = _describe_duckdb_table(ref)
    if cols is None:
        return None
    return [name for name, _type in cols]


def _extract_output_reference(result: Any, execution_id: str | None, node_id: str) -> dict | None:
    """Returns an output reference for the SSE event.

    Inclui ``database_path`` + ``table_name`` (+ ``dataset_name``) quando a
    referência DuckDB upstream foi reusada — caso típico de transform nodes
    (Mapper, Filter, Join, etc.) que escrevem suas tabelas no arquivo do
    upstream para evitar cópia desnecessária. Sem esses campos, o front só
    consegue resolver o preview via ``/executions/.../nodes/{node_id}/preview``,
    que assume ``{node_id}.duckdb`` — convenção quebrada para nós que não
    são donos do arquivo. Com os campos, o front cai no fluxo legado
    ``/nodes/duckdb-preview`` que aceita path explícito.
    """
    try:
        from app.data_pipelines.duckdb_storage import find_duckdb_reference  # noqa: PLC0415
        ref = find_duckdb_reference(result)
        if ref is not None:
            payload: dict[str, Any] = {
                "node_id": node_id,
                "storage_type": "duckdb",
            }
            db_path = ref.get("database_path")
            table_name = ref.get("table_name")
            dataset_name = ref.get("dataset_name")
            if db_path:
                payload["database_path"] = str(db_path)
            if table_name:
                payload["table_name"] = str(table_name)
            if dataset_name:
                payload["dataset_name"] = str(dataset_name)
            return payload
    except Exception:  # noqa: BLE001
        pass
    return None


async def _save_checkpoint_safe(
    execution_id: str,
    node_id: str,
    result: dict,
) -> None:
    """Salva checkpoint em background sem bloquear o runner.

    Importa checkpoint_service em tempo de execucao para evitar ciclo de
    importacao (runner <- services e checkpoint_service <- db.session).
    """
    try:
        from app.services import checkpoint_service  # noqa: PLC0415
        await checkpoint_service.save_checkpoint(execution_id, node_id, result)
    except Exception as exc:  # noqa: BLE001
        _logger = get_logger(__name__)
        _logger.warning(
            "checkpoint.background_save_failed",
            execution_id=execution_id,
            node_id=node_id,
            error=str(exc),
        )


async def run_workflow(
    workflow_payload: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    triggered_by: str = "manual",
    input_data: dict[str, Any] | None = None,
    execution_id: str | None = None,
    resolved_connections: dict[str, str] | None = None,
    variable_values: dict[str, Any] | None = None,
    *,
    event_sink: EventSink | None = None,
    mode: str = "production",
    target_node_id: str | None = None,
    call_stack: list[str] | None = None,
    max_depth: int = SUBWORKFLOW_MAX_DEPTH,
    in_loop: bool = False,
    checkpoint_results: dict[str, Any] | None = None,
    run_mode: str = "full",
    preview_max_rows: int | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """
    Entrypoint principal que orquestra a execucao dinamica de um workflow.

    Cada no e executado individualmente na ordem topologica do grafo.
    Nos do mesmo nivel sao executados em paralelo via ``asyncio.gather``.
    Nos de transformacao materializam dados em DuckDB e passam a referencia
    para o proximo no via contexto. O no de carga le o DuckDB e escreve
    no destino final.

    Pode receber o payload completo do workflow ou apenas o ID — permite
    que execucoes manuais/webhook e agendamentos cron compartilhem o
    mesmo entrypoint.

    Parametros de observabilidade
    -----------------------------
    - ``event_sink``: async callable que recebe um dict por evento de
      ciclo de vida. Quando ``None``, zero overhead (padrao para cron).
      Ver shape dos eventos no modulo-docstring.
    - ``mode``: ``"production"`` | ``"test"``, propagado para
      ``context["mode"]`` dos processadores. Ainda nao altera logica aqui;
      sera usado em Fase 2 (pinnedOutput/enabled).
    - ``target_node_id``: quando informado, o payload e recortado para
      conter apenas o no alvo e seus ancestrais antes da construcao do
      grafo. Usado pelo botao "testar ate aqui" do frontend.
    """
    logger = get_logger(__name__)

    # --- Sub-workflow guards ---------------------------------------
    # ``call_stack`` contem os workflow_ids ja em execucao na cadeia.
    # Detectamos ciclos antes de carregar o payload para evitar recursao
    # descontrolada; a verificacao de profundidade e um limite duro.
    incoming_stack = list(call_stack or [])
    if workflow_id and workflow_id in incoming_stack:
        cycle_path = " -> ".join(incoming_stack + [workflow_id])
        raise SubWorkflowCycleError(
            f"Ciclo detectado em call_workflow: {cycle_path}"
        )
    if len(incoming_stack) >= max_depth:
        raise SubWorkflowDepthError(
            f"Profundidade maxima de sub-workflows ({max_depth}) excedida: "
            f"{' -> '.join(incoming_stack)}"
        )
    current_stack = incoming_stack + ([workflow_id] if workflow_id else [])

    resolved_payload = await _resolve_workflow_payload(workflow_payload, workflow_id)
    resolved_payload = _filter_payload_to_ancestors(resolved_payload, target_node_id)
    execution_context: dict[str, Any] = {
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        # Identidade de tenant para o engine_cache: processadores que
        # criam engines via ``app.services.db.engine_cache.get_engine``
        # devem repassar este valor para que o cache isole pools por
        # workspace. ``None`` cai no DEFAULT_SCOPE — o que significa
        # cache compartilhado, util em testes e em flows sem contexto.
        "workspace_id": workspace_id,
        "triggered_by": triggered_by,
        "input_data": input_data or {},
        "vars": variable_values or {},
        "mode": mode,
        "call_stack": current_stack,
        "max_depth": max_depth,
        # Loop do runner (main loop do FastAPI). Processors sincronos que
        # precisam chamar codigo async com recursos ligados a este loop
        # (ex.: engine SQLAlchemy/asyncpg) devem usar
        # ``asyncio.run_coroutine_threadsafe(coro, _main_loop)`` em vez
        # de ``asyncio.run`` — o ultimo cria um loop novo e falha com
        # "Future attached to a different loop".
        "_main_loop": asyncio.get_running_loop(),
        # Marcador: este run foi disparado de dentro de um no ``loop``
        # (direto ou indireto). Usado pelo processor ``loop`` para
        # rejeitar loops aninhados ja na entrada do sub-workflow.
        "in_loop": bool(in_loop),
        # Acumulador populado pelos nos ``workflow_output`` — o pai que
        # chamou este run via ``call_workflow`` consome esse pacote.
        "workflow_output": {},
        # Event sink disponivel para processadores que queiram emitir
        # eventos intermediarios (ex.: ``loop`` publica ``node_progress``
        # por iteracao). Processadores devem sempre usar ``_safe_emit``
        # se precisarem emitir — o sink e None em cron/agendado e em
        # qualquer run sem observador anexado.
        "_event_sink": event_sink,
        "_execution_id": execution_id,
        # Modo de execucao selecionado pelo usuario no momento do disparo:
        # - ``full`` (padrao): roda tudo.
        # - ``preview``: processors de extracao aplicam LIMIT via
        #   ``_preview_max_rows`` — dry-run rapido para validar o pipeline.
        # - ``validate``: nao chega a invocar o runner (curto-circuito no
        #   ``workflow_service``), mas o campo fica disponivel para quem
        #   queira consultar.
        "run_mode": run_mode,
        "_preview_max_rows": (
            preview_max_rows if run_mode == "preview" else None
        ),
        # Connections ja resolvidas para este workflow — disponibilizadas
        # ao no ``loop`` em modo inline, que precisa repassa-las ao
        # sub-run do corpo embutido (mesmo workflow = mesmas connections).
        "_resolved_connections": resolved_connections or {},
    }

    nodes = resolved_payload.get("nodes", [])
    edges = resolved_payload.get("edges", [])

    # --- Fase 4: Parameter Resolver fail-fast ---
    # Resolve ${var} em todas as configs de nó antes de qualquer side effect.
    # Se alguma referência não for resolvida, marca execution como failed com
    # mensagem clara e retorna imediatamente (nenhum nó foi executado).
    _param_restorations: list = []
    if variable_values:
        try:
            from app.orchestration.flows.parameter_resolver import (  # noqa: PLC0415
                apply_parameters,
                ParameterError,
            )
            _param_restorations = apply_parameters(resolved_payload, variable_values)
        except Exception as _param_exc:  # noqa: BLE001
            # ParameterError ou inesperado — fail-fast antes de qualquer nó.
            _err_msg = str(_param_exc)
            logger.error("parameter_resolver.failed", error=_err_msg)
            return {
                "status": "failed",
                "error": _err_msg,
                "error_type": type(_param_exc).__name__,
                "node_results": {},
                "node_executions": [],
            }

    # ``workspace_id`` e ``workflow_id`` (= template_id no Shift) tambem entram
    # nos contextvars de log para que TODA mensagem dentro deste run tenha
    # esses campos — requisito de "logs estruturados com workspace/execution_id".
    with bind_context(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workspace_id=workspace_id,
    ), start_execution_span(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workspace_id=workspace_id,
        triggered_by=triggered_by,
    ):
        # Marcador de tempo do runner — usado para ``execution_duration_seconds``.
        # Diferente do ``started_at`` em DB porque queremos a duracao
        # **observada pelo runner**, sem o lag entre INSERT e dispatch.
        _exec_t0 = time.monotonic()
        logger.info(
            "workflow.start",
            node_count=len(nodes),
            edge_count=len(edges),
            triggered_by=triggered_by,
            mode=mode,
        )

        adjacency, reverse_adj, in_degree, node_map, edge_handle_map, target_handle_map = _build_graph(
            nodes, edges
        )
        levels = _topological_sort_levels(dict(in_degree), adjacency)

        logger.info("workflow.levels_computed", levels=len(levels))

        # --- Fase 4: ExecutionPlanSnapshot ---
        # Capturado imediatamente após topological sort, antes de rodar qualquer nó.
        # Persiste via event (quem chama run_workflow é responsável por salvar).
        try:
            from app.orchestration.flows.execution_plan import build_snapshot  # noqa: PLC0415
            _plan_snapshot = build_snapshot(nodes, edges, levels, execution_id)
            execution_context["_plan_snapshot"] = _plan_snapshot
            await _safe_emit(
                event_sink,
                {
                    "type": "execution_plan_ready",
                    "execution_id": execution_id,
                    "node_count": _plan_snapshot.node_count,
                    "edge_count": _plan_snapshot.edge_count,
                    "level_count": len(_plan_snapshot.levels),
                    "plan": _plan_snapshot.model_dump(mode="json"),
                },
                logger,
            )
        except Exception as _snap_exc:  # noqa: BLE001
            logger.warning("execution_plan.build_failed", error=str(_snap_exc))

        results: dict[str, dict[str, Any]] = {}
        node_executions: list[dict[str, Any]] = []
        node_timing: dict[str, dict[str, Any]] = {}
        # Hash semântico por nó — propagado downstream para que dois nós com
        # mesma config mas inputs diferentes produzam hashes diferentes.
        _node_semantic_hashes: dict[str, str] = {}

        # Estado acumulado para o evento ``execution_end`` — default
        # ``completed`` e sobrescrito em early-returns (failed/aborted) ou
        # no ``except CancelledError`` abaixo.
        final_status: str = "completed"

        def _record_event(
            node_id: str,
            node: dict[str, Any],
            status: str,
            *,
            duration_ms: int = 0,
            started_at: datetime | None = None,
            completed_at: datetime | None = None,
            row_count_in: int | None = None,
            row_count_out: int | None = None,
            output_summary: dict[str, Any] | None = None,
            error_message: str | None = None,
        ) -> None:
            """Registra um evento de execucao de no para persistir em DB."""
            now = datetime.now(timezone.utc)
            node_data_local = node.get("data", {}) if isinstance(node, dict) else {}
            label = node_data_local.get("label") or _get_node_type(node)
            node_type_local = _get_node_type(node)
            node_executions.append({
                "node_id": node_id,
                "node_type": node_type_local,
                "label": str(label)[:255] if label is not None else None,
                "status": status,
                "duration_ms": int(duration_ms),
                "row_count_in": row_count_in,
                "row_count_out": row_count_out,
                "output_summary": output_summary,
                "error_message": (error_message[:2000] if error_message else None),
                "started_at": started_at or now,
                "completed_at": completed_at or now,
            })

            # Metricas Prometheus por no — observamos sempre que o runner
            # registra um evento de no (success, error, handled_error,
            # skipped, cancelled). Skipped/cancelled nao incrementam erros;
            # error/handled_error incrementam ``node_errors_total`` e
            # tambem observam duracao (a observabilidade de "no que falhou
            # rapido" e tao util quanto a do que terminou bem).
            try:
                err_class: str | None = None
                if status in {"error", "handled_error"} and error_message:
                    if isinstance(output_summary, dict):
                        err_class = str(output_summary.get("error_type") or "Error")
                    else:
                        err_class = "Error"
                # ``record_node`` decide quais series tocar a partir dos
                # parametros nao-None. duration so quando temos timing real
                # (``duration_ms > 0``) — eventos triviais (skipped por
                # branch) tem duration 0 e nao agregam valor no histograma.
                record_node(
                    node_type=node_type_local,
                    duration_seconds=(duration_ms / 1000.0) if duration_ms else None,
                    rows_in=row_count_in,
                    rows_out=row_count_out,
                    error_class=err_class,
                )
            except Exception:  # noqa: BLE001
                pass

        # Controle de ramificacao condicional.
        # skipped_nodes: nos que nao devem ser executados porque todas as suas
        #   entradas sao inativas (por branch condicional ou cascata de skip).
        # inactive_edges: arestas (source, target) que partem de um handle nao
        #   ativado por um no de condicao.
        skipped_nodes: set[str] = set()
        inactive_edges: set[tuple[str, str]] = set()

        try:
            await _safe_emit(
                event_sink,
                {
                    "type": "execution_start",
                    "execution_id": execution_id,
                    "timestamp": _iso_now(),
                    "node_count": len(nodes),
                    "mode": mode,
                },
                logger,
            )

            for level_index, level in enumerate(levels):
                logger.info("workflow.level_start", level=level_index + 1, nodes=level)
                coros: list[tuple[str, Any]] = []

                for node_id in level:
                    node = node_map[node_id]
                    node_type_for_event, label_for_event = _event_node_meta(node)

                    # --- Verificacao de branch condicional ---
                    if _is_node_skipped(node_id, reverse_adj, skipped_nodes, inactive_edges):
                        with bind_context(node_id=node_id):
                            logger.info("node.skipped_by_branch")
                        skipped_nodes.add(node_id)
                        results[node_id] = {"node_id": node_id, "status": "skipped_by_branch"}
                        _record_event(
                            node_id,
                            node,
                            "skipped",
                            output_summary={"reason": "skipped_by_branch"},
                        )
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_skipped",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                "reason": "skipped_by_branch",
                            },
                            logger,
                        )
                        continue

                    node_data = node.get("data", {}) if isinstance(node.get("data"), dict) else {}

                    # --- checkpoint: reutiliza resultado de execucao anterior ---
                    checkpointed_result = (checkpoint_results or {}).get(node_id)
                    if isinstance(checkpointed_result, dict) and checkpointed_result:
                        chk_result = _default_success_handle_if_needed(
                            node_id,
                            checkpointed_result,
                            adjacency,
                            edge_handle_map,
                        )
                        with bind_context(node_id=node_id):
                            logger.info("node.checkpoint_restored")
                        results[node_id] = chk_result
                        row_in, row_out = _extract_row_counts(chk_result)
                        _record_event(
                            node_id,
                            node,
                            "skipped",
                            row_count_in=row_in,
                            row_count_out=row_out,
                            output_summary={"is_checkpoint": True},
                        )
                        _chk_ref = None
                        try:
                            from app.data_pipelines.duckdb_storage import find_duckdb_reference as _fdr  # noqa: PLC0415
                            _chk_ref = _fdr(chk_result)
                        except Exception:  # noqa: BLE001
                            pass
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_complete",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                "status": "success",
                                "row_count": row_out,
                                "schema_fingerprint": _compute_schema_fingerprint(_chk_ref),
                                "columns": _extract_output_columns(_chk_ref),
                                "output_reference": _extract_output_reference(chk_result, execution_id, node_id),
                                "duration_ms": 0,
                                "is_checkpoint": True,
                            },
                            logger,
                        )
                        continue

                    # --- Fase 5: StrategyResolver ativo ---
                    # Verifica cache (a menos que force_refresh=True), depois
                    # chama o resolver que decide se/como rodar o nó.
                    _force_refresh = bool(node_data.get("force_refresh", False))
                    _is_cache_hit = False
                    _cached_result_for_skip: dict | None = None

                    if node_data.get("cache_enabled") and not _force_refresh:
                        try:
                            from app.services.extract_cache_service import extract_cache_service as _ecs  # noqa: PLC0415
                            _cache_key = _ecs.make_cache_key(node_data)
                            _cached_result_for_skip = await _ecs.get(_cache_key, execution_id or "", node_id)
                            _is_cache_hit = _cached_result_for_skip is not None
                        except Exception:  # noqa: BLE001
                            logger.exception("node.cache_check_failed", node_id=node_id)

                    node_type = _get_node_type(node)
                    registered_processor_type = _get_registered_processor_type(node)

                    try:
                        from app.orchestration.flows.strategy_resolver import (  # noqa: PLC0415
                            resolve_strategy,
                            build_strategy_sse_event as _build_resolver_sse,
                        )
                        from app.services.workflow.semantic_hash import compute_semantic_hash  # noqa: PLC0415
                        _resolver_type = registered_processor_type or node_type
                        _resolver_decision = resolve_strategy(
                            node_id=node_id,
                            node_type=_resolver_type,
                            node_data=node_data,
                            run_mode=run_mode,
                            is_cache_hit=_is_cache_hit,
                            force_refresh=_force_refresh,
                        )
                        # Hash semântico — propaga fingerprints de upstreams
                        # para que mesma config com inputs diferentes gere hashes
                        # distintos. Sem isso, cache poisoning silencioso quando
                        # Fase 6+ usar o hash para skip.
                        _input_fps = sorted(
                            _node_semantic_hashes[pred_id]
                            for pred_id in reverse_adj.get(node_id, [])
                            if pred_id in _node_semantic_hashes
                        )
                        _sem_hash = compute_semantic_hash(
                            config=node_data,
                            input_fingerprints=_input_fps,
                            node_type=_resolver_type,
                        )
                        _node_semantic_hashes[node_id] = _sem_hash
                        await _safe_emit(
                            event_sink,
                            _build_resolver_sse(
                                node_id=node_id,
                                node_type=_resolver_type,
                                execution_id=execution_id,
                                decision=_resolver_decision,
                                label=label_for_event,
                                semantic_hash=_sem_hash,
                            ),
                            logger,
                        )
                    except Exception:  # noqa: BLE001
                        # Resolver nunca derruba execução. Fallback: sempre roda.
                        from app.orchestration.flows.strategy_resolver import StrategyDecision  # noqa: PLC0415
                        _resolver_decision = StrategyDecision(True, "local_thread", "resolver_error_fallback")
                        _sem_hash = None

                    # Se resolver diz SKIP (cache hit ou outro motivo):
                    if not _resolver_decision.should_run:
                        if _is_cache_hit and _cached_result_for_skip is not None:
                            _cached_r = _default_success_handle_if_needed(
                                node_id, _cached_result_for_skip, adjacency, edge_handle_map,
                            )
                            with bind_context(node_id=node_id):
                                logger.info("node.cache_hit")
                            results[node_id] = _cached_r
                            row_in, row_out = _extract_row_counts(_cached_r)
                            _record_event(
                                node_id, node, "skipped",
                                row_count_in=row_in, row_count_out=row_out,
                                output_summary={"is_cache_hit": True},
                            )
                            await _safe_emit(
                                event_sink,
                                {
                                    "type": "node_complete",
                                    "execution_id": execution_id,
                                    "timestamp": _iso_now(),
                                    "node_id": node_id,
                                    "node_type": node_type_for_event,
                                    "label": label_for_event,
                                    "status": "success",
                                    "row_count": row_out,
                                    "schema_fingerprint": None,
                                    "columns": _extract_output_columns(
                                        _extract_output_reference(_cached_r, execution_id, node_id)
                                    ),
                                    "output_reference": _extract_output_reference(_cached_r, execution_id, node_id),
                                    "duration_ms": 0,
                                    "is_cache_hit": True,
                                },
                                logger,
                            )
                        else:
                            with bind_context(node_id=node_id):
                                logger.info("node.strategy_skip", reason=_resolver_decision.reason)
                            results[node_id] = {"node_id": node_id, "status": "skipped", "reason": _resolver_decision.reason}
                            _record_event(node_id, node, "skipped", output_summary={"reason": _resolver_decision.reason})
                            await _safe_emit(
                                event_sink,
                                {
                                    "type": "node_skipped",
                                    "execution_id": execution_id,
                                    "timestamp": _iso_now(),
                                    "node_id": node_id,
                                    "node_type": node_type_for_event,
                                    "label": label_for_event,
                                    "reason": _resolver_decision.reason,
                                },
                                logger,
                            )
                        continue

                    # --- pinnedOutput: usa output fixado, nao chama processor ---
                    pinned_output = node_data.get("pinnedOutput")
                    if isinstance(pinned_output, dict) and pinned_output:
                        pinned_inner = _extract_pinned_output(pinned_output)
                        # v3 carrega linhas inline ({rows, columns, row_count}).
                        # Os processadores downstream (Mapper, Filter, Join...)
                        # esperam uma referência DuckDB via get_primary_input_reference.
                        # Materializamos as linhas em um arquivo .duckdb desta
                        # execução para que ``find_duckdb_reference`` encontre
                        # storage_type/database_path no upstream.
                        if pinned_output.get("__pinned_v") == 3 and pinned_inner.get("rows"):
                            from app.data_pipelines.duckdb_storage import ensure_duckdb_reference  # noqa: PLC0415
                            reference = ensure_duckdb_reference(
                                pinned_inner["rows"], execution_id, node_id
                            )
                            pinned_inner = {**pinned_inner, **reference}
                        pinned_result = _default_success_handle_if_needed(
                            node_id,
                            pinned_inner,
                            adjacency,
                            edge_handle_map,
                        )
                        with bind_context(node_id=node_id):
                            logger.info("node.pinned_output")
                        results[node_id] = pinned_result
                        row_in, row_out = _extract_row_counts(pinned_result)
                        # Emitimos node_start antes de node_complete para que o
                        # nó apareça na lista da ExecutionPanel — buildNodeStates
                        # só registra um nó quando vê node_start. Sem isto, o
                        # usuário não vê o nó pinado na timeline da execução.
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_start",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                            },
                            logger,
                        )
                        _record_event(
                            node_id,
                            node,
                            "success",
                            row_count_in=row_in,
                            row_count_out=row_out,
                            output_summary={"is_pinned": True},
                        )
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_complete",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                "status": "success",
                                "row_count": row_out,
                                "schema_fingerprint": None,
                                "columns": _extract_output_columns(
                                    _extract_output_reference(pinned_result, execution_id, node_id)
                                ),
                                "output_reference": _extract_output_reference(pinned_result, execution_id, node_id),
                                "duration_ms": 0,
                                "is_pinned": True,
                            },
                            logger,
                        )
                        continue

                    # --- enabled=False: pula execucao e propaga skip downstream ---
                    if node_data.get("enabled") is False:
                        with bind_context(node_id=node_id):
                            logger.info("node.disabled")
                        skipped_nodes.add(node_id)
                        results[node_id] = {
                            "node_id": node_id,
                            "status": "skipped",
                            "reason": "disabled",
                            "message": "No desativado.",
                        }
                        _record_event(
                            node_id,
                            node,
                            "skipped",
                            output_summary={"reason": "disabled"},
                        )
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_skipped",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                "reason": "disabled",
                            },
                            logger,
                        )
                        continue

                    # Apenas upstream ativos sao passados ao processador.
                    # Nos de juncao recebem somente os resultados dos caminhos ativos.
                    active_sources = [
                        source_id
                        for source_id in reverse_adj.get(node_id, [])
                        if source_id not in skipped_nodes
                        and (source_id, node_id) not in inactive_edges
                    ]
                    upstream_results = {
                        source_id: _route_upstream_result(
                            results.get(source_id, {}),
                            edge_handle_map.get((source_id, node_id)),
                        )
                        for source_id in active_sources
                    }
                    # edge_handles: {source_node_id -> targetHandle} para nos com multiplas
                    # entradas (join, lookup) identificarem qual upstream chegou em qual porta.
                    edge_handles = {
                        source_id: target_handle_map.get((source_id, node_id))
                        for source_id in active_sources
                    }

                    node_timeout = _resolve_node_timeout(node_data)

                    if registered_processor_type is not None:
                        with bind_context(node_id=node_id):
                            logger.info(
                                "node.dispatch_registered",
                                processor_type=registered_processor_type,
                                timeout_seconds=node_timeout,
                            )
                        # Injeta connection_string no config quando o no usa connection_id.
                        effective_config = _inject_connection_string(
                            node_data, resolved_connections or {}
                        )
                        processor_context = {
                            **execution_context,
                            "upstream_results": upstream_results,
                            "edge_handles": edge_handles,
                            # Todos os resultados executados ate agora (por referencia —
                            # reflete o estado vivo). Permite que _resolve_path acesse
                            # nos ancestrais nao-diretos via "upstream_results.<id>.*".
                            "_all_results": results,
                        }
                        node_timing[node_id] = {
                            "started_at": datetime.now(timezone.utc),
                            "t0": time.monotonic(),
                        }
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_start",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                            },
                            logger,
                        )
                        retry_policy = _parse_retry_policy(
                            effective_config.get("retry_policy")
                            if isinstance(effective_config, dict)
                            else None
                        )
                        _registered_type = registered_processor_type
                        _effective_config = effective_config
                        _processor_context = processor_context
                        coros.append((
                            node_id,
                            _run_with_retry(
                                node_id=node_id,
                                attempt_factory=lambda nid=node_id, ntype=_registered_type, cfg=_effective_config, ctx=_processor_context: execute_registered_node(
                                    node_id=nid,
                                    node_type=ntype,
                                    config=cfg,
                                    context=ctx,
                                ),
                                policy=retry_policy,
                                timeout=node_timeout,
                                logger=logger,
                                event_sink=event_sink,
                                execution_id=execution_id,
                                node_type_for_event=node_type_for_event,
                                label_for_event=label_for_event,
                            ),
                        ))
                        continue

                    if node_type == "aiNode":
                        with bind_context(node_id=node_id):
                            logger.info(
                                "node.dispatch_llm",
                                timeout_seconds=node_timeout,
                            )
                        node_timing[node_id] = {
                            "started_at": datetime.now(timezone.utc),
                            "t0": time.monotonic(),
                        }
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_start",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                            },
                            logger,
                        )
                        retry_policy = _parse_retry_policy(
                            node_data.get("retry_policy")
                            if isinstance(node_data, dict)
                            else None
                        )
                        _cfg = node_data
                        _inputs = upstream_results or None
                        coros.append((
                            node_id,
                            _run_with_retry(
                                node_id=node_id,
                                attempt_factory=lambda nid=node_id, cfg=_cfg, inp=_inputs: execute_llm_node(
                                    node_id=nid,
                                    config=cfg,
                                    input_data=inp,
                                ),
                                policy=retry_policy,
                                timeout=node_timeout,
                                logger=logger,
                                event_sink=event_sink,
                                execution_id=execution_id,
                                node_type_for_event=node_type_for_event,
                                label_for_event=label_for_event,
                            ),
                        ))
                        continue

                    with bind_context(node_id=node_id):
                        logger.warning("node.unknown_type", node_type=node_type)
                    # Registra como skipped para manter rastreabilidade em DB.
                    _record_event(
                        node_id,
                        node,
                        "skipped",
                        output_summary={
                            "reason": "unknown_type",
                            "node_type": node_type,
                        },
                    )
                    await _safe_emit(
                        event_sink,
                        {
                            "type": "node_skipped",
                            "execution_id": execution_id,
                            "timestamp": _iso_now(),
                            "node_id": node_id,
                            "node_type": node_type_for_event,
                            "label": label_for_event,
                            "reason": "unknown_type",
                        },
                        logger,
                    )

                if not coros:
                    continue

                # Executa nos do nivel em paralelo; cada excecao retorna como valor.
                node_ids = [nid for nid, _ in coros]
                gathered = await asyncio.gather(
                    *(c for _, c in coros), return_exceptions=True
                )

                # Processa TODOS os outcomes do nivel antes de decidir parada.
                # ``asyncio.gather`` ja esperou todos, mas o early-return antigo
                # abortava a funcao no primeiro erro e nunca emitia os eventos
                # terminais dos irmaos — a UI ficava com nos em "executando"
                # para sempre. Acumulamos paradas (skipped / failed / reraise)
                # e aplicamos no final, mas emitimos node_complete/node_error/
                # node_skipped/node_error_handled para cada no.
                level_skipped: list[tuple[str, NodeProcessingSkipped]] = []
                level_failed: list[tuple[str, NodeProcessingError]] = []
                level_unexpected: list[tuple[str, BaseException]] = []

                for node_id, outcome in zip(node_ids, gathered):
                    timing = node_timing.get(node_id, {})
                    started_at = timing.get("started_at") or datetime.now(timezone.utc)
                    t0 = timing.get("t0")
                    duration_ms = (
                        int((time.monotonic() - t0) * 1000) if t0 is not None else 0
                    )
                    completed_at = datetime.now(timezone.utc)
                    node_for_event = node_map[node_id]
                    node_type_for_event, label_for_event = _event_node_meta(
                        node_for_event
                    )

                    with bind_context(node_id=node_id):
                        if isinstance(outcome, NodeProcessingSkipped):
                            logger.info(
                                "workflow.aborted_gracefully", reason=str(outcome)
                            )
                            _record_event(
                                node_id,
                                node_for_event,
                                "skipped",
                                duration_ms=duration_ms,
                                started_at=started_at,
                                completed_at=completed_at,
                                error_message=str(outcome),
                                output_summary={"reason": "aborted_gracefully"},
                            )
                            await _safe_emit(
                                event_sink,
                                {
                                    "type": "node_skipped",
                                    "execution_id": execution_id,
                                    "timestamp": _iso_now(),
                                    "node_id": node_id,
                                    "node_type": node_type_for_event,
                                    "label": label_for_event,
                                    "reason": "aborted_gracefully",
                                    "duration_ms": duration_ms,
                                },
                                logger,
                            )
                            level_skipped.append((node_id, outcome))
                            continue

                        if isinstance(outcome, NodeProcessingError):
                            # Fase 5b: se o no tem aresta saindo do handle
                            # "on_error", convertemos a falha em resultado
                            # ``handled_error`` e rotamos pelo ramo de erro
                            # em vez de abortar o workflow. Caso contrario,
                            # o erro entra em ``level_failed`` e, apos emitir
                            # eventos de todos os irmaos, o workflow aborta.
                            has_error_branch = any(
                                edge_handle_map.get((node_id, target)) == "on_error"
                                for target in adjacency.get(node_id, [])
                            )
                            if has_error_branch:
                                logger.info(
                                    "node.error_handled", error=str(outcome)
                                )
                                handled_result = {
                                    "status": "handled_error",
                                    "active_handle": "on_error",
                                    "error": str(outcome),
                                    "error_type": outcome.__class__.__name__,
                                    "failed_node": node_id,
                                }
                                results[node_id] = handled_result
                                # Desativa todas as arestas de saida que nao
                                # sao o handle "on_error".
                                for target_id in adjacency.get(node_id, []):
                                    edge_handle = edge_handle_map.get(
                                        (node_id, target_id)
                                    )
                                    if edge_handle != "on_error":
                                        inactive_edges.add((node_id, target_id))
                                _record_event(
                                    node_id,
                                    node_for_event,
                                    "handled_error",
                                    duration_ms=duration_ms,
                                    started_at=started_at,
                                    completed_at=completed_at,
                                    error_message=str(outcome),
                                    output_summary={
                                        "error_type": outcome.__class__.__name__,
                                        "active_handle": "on_error",
                                    },
                                )
                                await _safe_emit(
                                    event_sink,
                                    {
                                        "type": "node_error_handled",
                                        "execution_id": execution_id,
                                        "timestamp": _iso_now(),
                                        "node_id": node_id,
                                        "node_type": node_type_for_event,
                                        "label": label_for_event,
                                        "error": str(outcome),
                                        "error_type": outcome.__class__.__name__,
                                        "duration_ms": duration_ms,
                                    },
                                    logger,
                                )
                                continue  # nao aborta o workflow

                            logger.error("node.failed", error=str(outcome))
                            _record_event(
                                node_id,
                                node_for_event,
                                "error",
                                duration_ms=duration_ms,
                                started_at=started_at,
                                completed_at=completed_at,
                                error_message=str(outcome),
                            )
                            # Extrai sample de linha problematica do details
                            # da excecao — o log service mascara PII antes
                            # de gravar em ``workflow_execution_logs.context``.
                            error_event: dict[str, Any] = {
                                "type": "node_error",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                "error": str(outcome),
                                "duration_ms": duration_ms,
                            }
                            outcome_details = getattr(outcome, "details", None)
                            if isinstance(outcome_details, dict):
                                sample = outcome_details.get("failed_row_sample")
                                if isinstance(sample, (dict, list)):
                                    error_event["failed_row_sample"] = sample
                                extra_ctx = outcome_details.get("context")
                                if isinstance(extra_ctx, dict):
                                    error_event["error_context"] = extra_ctx
                            await _safe_emit(event_sink, error_event, logger)
                            level_failed.append((node_id, outcome))
                            continue

                        if isinstance(outcome, BaseException):
                            # Erros inesperados — registra evento antes de propagar
                            # para que _persist_final_state ainda tenha contexto
                            # minimo (via caller que captura node_executions do
                            # result parcial, se disponivel). O re-raise mantem o
                            # comportamento atual: a execucao e marcada como
                            # FAILED/CANCELLED pelo workflow_service. Acumula
                            # para re-raise apos drenar eventos do nivel.
                            _record_event(
                                node_id,
                                node_for_event,
                                "error",
                                duration_ms=duration_ms,
                                started_at=started_at,
                                completed_at=completed_at,
                                error_message=f"{type(outcome).__name__}: {outcome}",
                            )
                            await _safe_emit(
                                event_sink,
                                {
                                    "type": "node_error",
                                    "execution_id": execution_id,
                                    "timestamp": _iso_now(),
                                    "node_id": node_id,
                                    "node_type": node_type_for_event,
                                    "label": label_for_event,
                                    "error": f"{type(outcome).__name__}: {outcome}",
                                    "duration_ms": duration_ms,
                                },
                                logger,
                            )
                            level_unexpected.append((node_id, outcome))
                            continue

                        result = _default_success_handle_if_needed(
                            node_id,
                            outcome,
                            adjacency,
                            edge_handle_map,
                        )
                        results[node_id] = result

                        row_in, row_out = _extract_row_counts(result)
                        output_summary = _summarize_result(result)
                        _record_event(
                            node_id,
                            node_for_event,
                            "success",
                            duration_ms=duration_ms,
                            started_at=started_at,
                            completed_at=completed_at,
                            row_count_in=row_in,
                            row_count_out=row_out,
                            output_summary=output_summary,
                        )
                        _result_ref = None
                        try:
                            from app.data_pipelines.duckdb_storage import find_duckdb_reference as _fdr2  # noqa: PLC0415
                            _result_ref = _fdr2(result)
                        except Exception:  # noqa: BLE001
                            pass
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_complete",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                # Lean payload: sem dados completos do output.
                                # Frontend busca via GET /executions/{eid}/nodes/{nid}/preview
                                # quando o usuario seleciona o no no painel de execucao.
                                # Status reflete erro/parcial reportado pelo processor:
                                # bulk_insert/loadNode podem aceitar a chamada mas terem
                                # 100% de linhas falhando — sem isso o usuario ve "ok"
                                # na UI mesmo com 0 linhas inseridas.
                                **(lambda s, fc: {
                                    "status": s,
                                    **({"failed_rows_count": fc} if fc else {}),
                                    **(
                                        {"error": _extract_error_summary(result, s, fc)}
                                        if _extract_error_summary(result, s, fc)
                                        else {}
                                    ),
                                })(*_derive_node_status(result)),
                                "row_count": row_out,
                                "schema_fingerprint": _compute_schema_fingerprint(_result_ref),
                                "columns": _extract_output_columns(_result_ref),
                                "output_reference": _extract_output_reference(result, execution_id, node_id),
                                "duration_ms": duration_ms,
                            },
                            logger,
                        )

                        # Salva checkpoint se o no tiver checkpoint_enabled=true.
                        # Roda em background para nao bloquear o fluxo.
                        node_for_chk = node_map.get(node_id, {})
                        node_data_for_chk = node_for_chk.get("data", {}) if isinstance(node_for_chk, dict) else {}
                        if isinstance(node_data_for_chk, dict) and node_data_for_chk.get("checkpoint_enabled") and execution_id:
                            asyncio.create_task(
                                _save_checkpoint_safe(execution_id, node_id, result)
                            )

                        # Salva no cache de extracoes quando cache_enabled=True.
                        if isinstance(node_data_for_chk, dict) and node_data_for_chk.get("cache_enabled") and execution_id:
                            _cache_ttl = int(node_data_for_chk.get("cache_ttl_seconds") or 300)
                            _node_type_for_cache = str(node_for_chk.get("type", "unknown"))

                            async def _save_cache_safe(
                                _nd=node_data_for_chk,
                                _r=result,
                                _nt=_node_type_for_cache,
                                _ttl=_cache_ttl,
                                _eid=execution_id,
                                _nid=node_id,
                            ) -> None:
                                try:
                                    from app.services.extract_cache_service import extract_cache_service as _ecs  # noqa: PLC0415
                                    _key = _ecs.make_cache_key(_nd)
                                    await _ecs.save(_key, _r, _nt, _ttl, _eid)
                                except Exception:  # noqa: BLE001
                                    logger.exception("node.cache_save_failed", node_id=_nid)

                            asyncio.create_task(_save_cache_safe())

                        # Se o no retornou active_handle(s) (no de condicao), marca como
                        # inativas todas as arestas de saida cujo sourceHandle nao esta
                        # no conjunto ativo. Suporta duas formas:
                        #   - ``active_handle``  (str):     all-or-nothing (ifElse/switch)
                        #   - ``active_handles`` (list):    row-partition (if_node/switch_node)
                        active_handles_set: set[str] | None = None
                        active_handles_raw = result.get("active_handles")
                        if isinstance(active_handles_raw, (list, tuple, set)):
                            active_handles_set = {str(h) for h in active_handles_raw}
                        else:
                            active_handle = result.get("active_handle")
                            if active_handle is not None:
                                active_handles_set = {str(active_handle)}

                        if active_handles_set is not None:
                            for target_id in adjacency.get(node_id, []):
                                edge_handle = edge_handle_map.get((node_id, target_id))
                                if edge_handle is not None and edge_handle not in active_handles_set:
                                    inactive_edges.add((node_id, target_id))
                                    logger.info(
                                        "edge.inactivated",
                                        target=target_id,
                                        handle=edge_handle,
                                        active_handles=sorted(active_handles_set),
                                    )

                # Com todos os eventos do nivel emitidos, decide se o workflow
                # deve parar. Ordem de prioridade: unexpected (re-raise) >
                # skipped (aborted gracefully) > failed (early-return).
                if level_unexpected:
                    first_id, first_exc = level_unexpected[0]
                    final_status = "failed"
                    logger.error(
                        "workflow.aborted_by_unexpected",
                        failed_by=first_id,
                        extra_failures=len(level_unexpected) - 1,
                    )
                    raise first_exc
                if level_skipped:
                    first_id, first_exc = level_skipped[0]
                    final_status = "aborted"
                    return {
                        "status": "aborted",
                        "aborted_by": first_id,
                        "reason": str(first_exc),
                        "node_results": results,
                        "node_executions": node_executions,
                    }
                if level_failed:
                    first_id, first_exc = level_failed[0]
                    final_status = "failed"
                    return {
                        "status": "failed",
                        "failed_by": first_id,
                        "error": str(first_exc),
                        "node_results": results,
                        "node_executions": node_executions,
                    }

            logger.info("workflow.completed", node_count=len(results))
            final_status = "completed"
            _snap = execution_context.get("_plan_snapshot")
            return {
                "status": "completed",
                "node_results": results,
                "node_executions": node_executions,
                "workflow_output": dict(execution_context.get("workflow_output", {})),
                "plan_snapshot": _snap.model_dump(mode="json") if _snap is not None else None,
            }
        except asyncio.CancelledError:
            final_status = "cancelled"
            # Registra "cancelled" para nos que iniciaram mas nao concluiram.
            completed_node_ids = {evt["node_id"] for evt in node_executions}
            _now_cancel = datetime.now(timezone.utc)
            for nid, timing in node_timing.items():
                if nid not in completed_node_ids:
                    node_for_cancel = node_map.get(nid, {})
                    t0_c = timing.get("t0")
                    duration_ms_c = (
                        int((time.monotonic() - t0_c) * 1000)
                        if t0_c is not None
                        else 0
                    )
                    _record_event(
                        nid,
                        node_for_cancel,
                        "cancelled",
                        duration_ms=duration_ms_c,
                        started_at=timing.get("started_at") or _now_cancel,
                        completed_at=_now_cancel,
                        error_message="Execucao cancelada pelo usuario.",
                    )
            raise
        except BaseException:
            # Excecao inesperada nao tratada nos ramos acima — garante que
            # execution_end reflita "failed".
            if final_status == "completed":
                final_status = "failed"
            raise
        finally:
            # Restaura ${var} no resolved_payload para que o dict não fique
            # mutado in-place. Importante quando o payload pode ser reusado
            # (loop inline, sub-workflow). Sem isso, segunda passada veria
            # valores já resolvidos em vez do template original.
            if _param_restorations:
                try:
                    from app.orchestration.flows.parameter_resolver import (  # noqa: PLC0415
                        restore_parameters,
                    )
                    restore_parameters(_param_restorations)
                except Exception:  # noqa: BLE001
                    logger.exception("parameter_resolver.restore_failed")
            # Evento especifico de cancelamento (antes de execution_end)
            if final_status == "cancelled":
                await _safe_emit(
                    event_sink,
                    {
                        "type": "execution.cancelled",
                        "execution_id": execution_id,
                        "timestamp": _iso_now(),
                    },
                    logger,
                )
            await _safe_emit(
                event_sink,
                {
                    "type": "execution_end",
                    "execution_id": execution_id,
                    "timestamp": _iso_now(),
                    "status": final_status,
                },
                logger,
            )
            # Metrica Prometheus de fim de execucao. Sempre emitida — em
            # qualquer caminho de saida (success, failed, cancelled, aborted).
            try:
                record_execution(
                    workspace_id=workspace_id,
                    template_id=workflow_id,
                    status=final_status,
                    duration_seconds=time.monotonic() - _exec_t0,
                )
            except Exception:  # noqa: BLE001
                logger.exception("metrics.record_execution_failed")
            # Remove arquivos DuckDB temporarios desta execucao.
            # Pulado em mode="test" porque o frontend ainda precisa
            # chamar /nodes/duckdb-preview pra renderizar a aba "Tabela"
            # depois que o stream SSE termina. Esses arquivos sao limpos
            # depois pelo job ``cleanup_orphaned_executions`` no proximo
            # boot do backend, OU pelo cleanup do tempdir do SO.
            if execution_id and mode != "test":
                try:
                    from app.data_pipelines.duckdb_storage import (  # noqa: PLC0415
                        cleanup_execution_storage,
                    )
                    cleanup_execution_storage(execution_id)
                except Exception as _exc:  # noqa: BLE001
                    logger.warning(
                        "execution.storage_cleanup_failed",
                        execution_id=execution_id,
                        error=str(_exc),
                    )
                # Cleanup de spillover do streaming (Prompt 1.2). Cobre os
                # arquivos que sobreviveram a uma queue.cleanup() — defesa
                # em profundidade caso algum caller esqueca de fechar.
                try:
                    from app.services.streaming import (  # noqa: PLC0415
                        cleanup_execution_spill,
                    )
                    removed = cleanup_execution_spill(execution_id)
                    if removed:
                        logger.info(
                            "execution.spill_cleanup",
                            execution_id=execution_id,
                            removed=removed,
                        )
                except Exception as _exc:  # noqa: BLE001
                    logger.warning(
                        "execution.spill_cleanup_failed",
                        execution_id=execution_id,
                        error=str(_exc),
                    )
