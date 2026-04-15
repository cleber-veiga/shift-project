"""
Orquestrador dinamico de workflows.

Recebe o payload do React Flow (nodes + edges), constroi a ordem de
execucao via ordenacao topologica e despacha as tasks Prefect
correspondentes a cada tipo de no.

Cada no e executado individualmente pelo registry de processors.
Nos de transformacao (math, filter, mapper, aggregator) materializam
seus resultados em DuckDB, que e passado adiante como referencia.
O no de carga (loadNode) le o DuckDB e escreve no destino final via dlt.

Ramificacao condicional
-----------------------
Nos de condicao (ifElse, switch) retornam ``active_handle`` em seu resultado,
indicando qual porta de saida foi ativada. O runner mapeia esse valor contra o
``sourceHandle`` de cada aresta de saida do no:

- Arestas cujo ``sourceHandle`` nao corresponde ao ``active_handle`` sao
  adicionadas a ``inactive_edges``.
- Nos cujas TODAS as entradas estao em ``inactive_edges`` ou em
  ``skipped_nodes`` sao marcados com ``status: "skipped_by_branch"`` e nao
  sao executados. Esse estado se propaga em cascata para os descendentes.
- Nos de juncao com ao menos uma entrada ativa sao executados normalmente,
  recebendo apenas os resultados upstream ativos no contexto.
"""

import asyncio
from collections import defaultdict, deque
from typing import Any
from uuid import UUID

from prefect import flow, get_run_logger

from app.db.session import async_session_factory
from app.models.workflow import Workflow
from app.orchestration.tasks.llm_task import execute_llm_node
from app.orchestration.tasks.node_processor import execute_registered_node
from app.services.workflow.nodes import has_processor
from app.services.workflow.nodes.exceptions import (
    NodeProcessingError,
    NodeProcessingSkipped,
)


async def _load_workflow_payload_from_db(workflow_id: UUID) -> dict[str, Any]:
    """Carrega a definicao do workflow do banco para execucoes agendadas."""
    async with async_session_factory() as session:
        from sqlalchemy import select
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


def _resolve_workflow_payload(
    workflow_payload: dict[str, Any] | None,
    workflow_id: str | None,
) -> dict[str, Any]:
    """Resolve o payload do workflow, carregando-o do banco quando necessario."""
    if workflow_payload is not None:
        return workflow_payload

    if workflow_id is None:
        raise ValueError(
            "workflow_payload ou workflow_id deve ser informado para executar o flow."
        )

    return asyncio.run(_load_workflow_payload_from_db(UUID(workflow_id)))


@flow(name="dynamic-runner", retries=0, log_prints=True)
def run_workflow(
    workflow_payload: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    triggered_by: str = "manual",
    input_data: dict[str, Any] | None = None,
    execution_id: str | None = None,
    resolved_connections: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Flow principal que orquestra a execucao dinamica de um workflow.

    Cada no e executado individualmente na ordem topologica do grafo.
    Nos de transformacao materializam dados em DuckDB e passam a referencia
    para o proximo no via contexto. O no de carga le o DuckDB e escreve
    no destino final.

    O flow pode receber o payload completo do workflow ou apenas o ID.
    Isso permite que execucoes manuais/webhook e agendamentos cron
    compartilhem a mesma flow principal.
    """
    logger = get_run_logger()
    resolved_payload = _resolve_workflow_payload(workflow_payload, workflow_id)
    execution_context: dict[str, Any] = {
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "triggered_by": triggered_by,
        "input_data": input_data or {},
    }

    nodes = resolved_payload.get("nodes", [])
    edges = resolved_payload.get("edges", [])

    logger.info(f"Iniciando workflow com {len(nodes)} nos e {len(edges)} arestas.")

    adjacency, reverse_adj, in_degree, node_map, edge_handle_map, target_handle_map = _build_graph(
        nodes, edges
    )
    levels = _topological_sort_levels(dict(in_degree), adjacency)

    logger.info(f"Niveis de execucao: {len(levels)}")

    results: dict[str, dict[str, Any]] = {}

    # Controle de ramificacao condicional.
    # skipped_nodes: nos que nao devem ser executados porque todas as suas
    #   entradas sao inativas (por branch condicional ou cascata de skip).
    # inactive_edges: arestas (source, target) que partem de um handle nao
    #   ativado por um no de condicao.
    skipped_nodes: set[str] = set()
    inactive_edges: set[tuple[str, str]] = set()

    for level_index, level in enumerate(levels):
        logger.info(f"Nivel {level_index + 1}: {level}")
        futures: list[tuple[str, Any]] = []

        for node_id in level:
            # --- Verificacao de branch condicional ---
            if _is_node_skipped(node_id, reverse_adj, skipped_nodes, inactive_edges):
                logger.info(
                    f"No '{node_id}' ignorado por ramificacao condicional (skipped_by_branch)."
                )
                skipped_nodes.add(node_id)
                results[node_id] = {"node_id": node_id, "status": "skipped_by_branch"}
                continue

            node = node_map[node_id]
            node_data = node.get("data", {})
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
                source_id: results.get(source_id, {})
                for source_id in active_sources
            }
            # edge_handles: {source_node_id -> targetHandle} para nos com multiplas
            # entradas (join, lookup) identificarem qual upstream chegou em qual porta.
            edge_handles = {
                source_id: target_handle_map.get((source_id, node_id))
                for source_id in active_sources
            }

            if registered_processor_type is not None:
                logger.info(
                    f"Executando no registrado: {node_id} ({registered_processor_type})"
                )
                # Injeta connection_string no config quando o no usa connection_id.
                # Os processadores continuam lendo config["connection_string"] sem alteracoes.
                effective_config = _inject_connection_string(
                    node_data, resolved_connections or {}
                )
                processor_context = {
                    **execution_context,
                    "upstream_results": upstream_results,
                    "edge_handles": edge_handles,
                }
                future = execute_registered_node.submit(
                    node_id=node_id,
                    node_type=registered_processor_type,
                    config=effective_config,
                    context=processor_context,
                )
                futures.append((node_id, future))
                continue

            if node_type == "aiNode":
                logger.info(f"AI/LLM: {node_id}")
                future = execute_llm_node.submit(
                    node_id=node_id,
                    config=node_data,
                    input_data=upstream_results or None,
                )
                futures.append((node_id, future))
                continue

            logger.warning(
                f"Tipo de no desconhecido '{node_type}' no no '{node_id}'. Ignorando."
            )

        for node_id, future in futures:
            try:
                result = future.result()
            except NodeProcessingSkipped as exc:
                logger.info(
                    f"Workflow abortado graciosamente pelo no '{node_id}': {exc}"
                )
                return {
                    "status": "aborted",
                    "aborted_by": node_id,
                    "reason": str(exc),
                    "node_results": results,
                }
            except NodeProcessingError as exc:
                logger.error(f"Falha funcional no no '{node_id}': {exc}")
                return {
                    "status": "failed",
                    "failed_by": node_id,
                    "error": str(exc),
                    "node_results": results,
                }

            results[node_id] = result

            # Se o no retornou active_handle (no de condicao), marca como inativas
            # todas as arestas de saida cujo sourceHandle nao corresponde ao handle ativo.
            active_handle = result.get("active_handle")
            if active_handle is not None:
                active_handle_str = str(active_handle)
                for target_id in adjacency.get(node_id, []):
                    edge_handle = edge_handle_map.get((node_id, target_id))
                    if edge_handle is not None and edge_handle != active_handle_str:
                        inactive_edges.add((node_id, target_id))
                        logger.info(
                            f"Aresta '{node_id}' -> '{target_id}' (handle='{edge_handle}') "
                            f"inativada: handle ativo e '{active_handle_str}'."
                        )

    logger.info(f"Workflow concluido com {len(results)} nos processados.")
    return {"status": "completed", "node_results": results}
