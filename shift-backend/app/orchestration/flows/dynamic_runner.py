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
node_error, node_skipped, execution_end) para o sink — usado pelo
``workflow_test_service`` para transformar em SSE. Quando ``None``
(padrao em execucoes cron), nao ha overhead.

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
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import bind_context, get_logger
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
# (seja por tamanho, seja por conterem estruturas nao serializaveis).
_OUTPUT_SUMMARY_DROP_KEYS = frozenset({"rows", "data", "upstream_results"})


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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_workflow(
    workflow_payload: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    triggered_by: str = "manual",
    input_data: dict[str, Any] | None = None,
    execution_id: str | None = None,
    resolved_connections: dict[str, str] | None = None,
    *,
    event_sink: EventSink | None = None,
    mode: str = "production",
    target_node_id: str | None = None,
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
    resolved_payload = await _resolve_workflow_payload(workflow_payload, workflow_id)
    resolved_payload = _filter_payload_to_ancestors(resolved_payload, target_node_id)
    execution_context: dict[str, Any] = {
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "triggered_by": triggered_by,
        "input_data": input_data or {},
        "mode": mode,
    }

    nodes = resolved_payload.get("nodes", [])
    edges = resolved_payload.get("edges", [])

    with bind_context(execution_id=execution_id, workflow_id=workflow_id):
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

        results: dict[str, dict[str, Any]] = {}
        node_executions: list[dict[str, Any]] = []
        node_timing: dict[str, dict[str, Any]] = {}

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
            node_executions.append({
                "node_id": node_id,
                "node_type": _get_node_type(node),
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

                    # --- pinnedOutput: usa output fixado, nao chama processor ---
                    pinned_output = node_data.get("pinnedOutput")
                    if isinstance(pinned_output, dict) and pinned_output:
                        with bind_context(node_id=node_id):
                            logger.info("node.pinned_output")
                        results[node_id] = pinned_output
                        row_in, row_out = _extract_row_counts(pinned_output)
                        _record_event(
                            node_id,
                            node,
                            "skipped",
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
                                "output": pinned_output,
                                "duration_ms": 0,
                                "is_pinned": True,
                                "row_count_in": row_in,
                                "row_count_out": row_out,
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

                    node_type = _get_node_type(node)
                    registered_processor_type = _get_registered_processor_type(node)

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
                        coros.append((
                            node_id,
                            _run_with_timeout(
                                node_id=node_id,
                                coro=execute_registered_node(
                                    node_id=node_id,
                                    node_type=registered_processor_type,
                                    config=effective_config,
                                    context=processor_context,
                                ),
                                timeout=node_timeout,
                                logger=logger,
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
                        coros.append((
                            node_id,
                            _run_with_timeout(
                                node_id=node_id,
                                coro=execute_llm_node(
                                    node_id=node_id,
                                    config=node_data,
                                    input_data=upstream_results or None,
                                ),
                                timeout=node_timeout,
                                logger=logger,
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
                            final_status = "aborted"
                            return {
                                "status": "aborted",
                                "aborted_by": node_id,
                                "reason": str(outcome),
                                "node_results": results,
                                "node_executions": node_executions,
                            }
                        if isinstance(outcome, NodeProcessingError):
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
                            await _safe_emit(
                                event_sink,
                                {
                                    "type": "node_error",
                                    "execution_id": execution_id,
                                    "timestamp": _iso_now(),
                                    "node_id": node_id,
                                    "node_type": node_type_for_event,
                                    "label": label_for_event,
                                    "error": str(outcome),
                                    "duration_ms": duration_ms,
                                },
                                logger,
                            )
                            final_status = "failed"
                            return {
                                "status": "failed",
                                "failed_by": node_id,
                                "error": str(outcome),
                                "node_results": results,
                                "node_executions": node_executions,
                            }
                        if isinstance(outcome, BaseException):
                            # Erros inesperados — registra evento antes de propagar
                            # para que _persist_final_state ainda tenha contexto
                            # minimo (via caller que captura node_executions do
                            # result parcial, se disponivel). O re-raise mantem o
                            # comportamento atual: a execucao e marcada como
                            # FAILED/CANCELLED pelo workflow_service.
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
                            final_status = "failed"
                            raise outcome

                        result = outcome
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
                        await _safe_emit(
                            event_sink,
                            {
                                "type": "node_complete",
                                "execution_id": execution_id,
                                "timestamp": _iso_now(),
                                "node_id": node_id,
                                "node_type": node_type_for_event,
                                "label": label_for_event,
                                "output": output_summary,
                                "duration_ms": duration_ms,
                                "row_count_in": row_in,
                                "row_count_out": row_out,
                            },
                            logger,
                        )

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

            logger.info("workflow.completed", node_count=len(results))
            final_status = "completed"
            return {
                "status": "completed",
                "node_results": results,
                "node_executions": node_executions,
            }
        except asyncio.CancelledError:
            final_status = "cancelled"
            raise
        except BaseException:
            # Excecao inesperada nao tratada nos ramos acima — garante que
            # execution_end reflita "failed".
            if final_status == "completed":
                final_status = "failed"
            raise
        finally:
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
