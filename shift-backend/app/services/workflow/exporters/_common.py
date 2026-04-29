"""Helpers compartilhados pelos exportadores SQL e Python."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.orchestration.flows.node_profile import NODE_EXECUTION_PROFILE


# ---------------------------------------------------------------------------
# Substituicao de placeholders
# ---------------------------------------------------------------------------

# Templates do runtime: ``{{vars.NOME}}``. Convertidos para ``${NOME}`` no
# output dos exportadores (estilo shell/dotenv) — formato amplamente aceito
# por scripts de orquestracao e por substituicao manual.
_VARS_TEMPLATE_RE = re.compile(r"\{\{\s*vars\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def collect_referenced_vars(definition: dict[str, Any]) -> dict[str, list[str]]:
    """Mapeia variavel -> lista de node_ids que a referenciam."""
    refs: dict[str, set[str]] = defaultdict(set)
    nodes = definition.get("nodes") or []
    for node in nodes:
        node_id = str(node.get("id") or "")

        def _walk(value: Any) -> None:
            if isinstance(value, str):
                for name in _VARS_TEMPLATE_RE.findall(value):
                    refs[name].add(node_id)
            elif isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for v in value:
                    _walk(v)

        _walk(node.get("data") or {})

    return {name: sorted(node_ids) for name, node_ids in refs.items()}


def render_var_placeholders(text: str) -> str:
    """Converte ``{{vars.X}}`` -> ``${X}`` em strings exportadas."""
    return _VARS_TEMPLATE_RE.sub(lambda m: f"${{{m.group(1)}}}", text)


# ---------------------------------------------------------------------------
# Identificacao de conexoes
# ---------------------------------------------------------------------------

def collect_connections(definition: dict[str, Any]) -> dict[str, list[str]]:
    """Mapeia connection_id (string) -> lista de node_ids que a usam."""
    conns: dict[str, set[str]] = defaultdict(set)
    for node in definition.get("nodes") or []:
        data = node.get("data") or {}
        cid = data.get("connection_id")
        if not cid:
            continue
        if isinstance(cid, UUID):
            cid_str = str(cid)
        else:
            cid_str = str(cid)
        conns[cid_str].add(str(node.get("id") or ""))
    return {cid: sorted(node_ids) for cid, node_ids in conns.items()}


def short_connection_alias(connection_id: str) -> str:
    """Gera alias curto e estavel para um connection_id (UUID ou template)."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", connection_id)
    if not cleaned:
        return "conn"
    return f"conn_{cleaned[:8].lower()}"


# ---------------------------------------------------------------------------
# Topological sort (versao auto-contida — nao acopla com orchestration)
# ---------------------------------------------------------------------------

def build_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, int],
    dict[str, dict[str, Any]],
    dict[tuple[str, str], str | None],
]:
    """Constroi adjacencia/grau + mapa de target_handle por aresta.

    Diferente de ``orchestration.flows.dynamic_runner._build_graph``, aqui
    so precisamos do target_handle (que upstream chega em qual porta do nó
    de destino) — sourceHandle nao influencia exportacao porque apenas
    ifElse/switch o usam para escolher ramos em runtime, e esses nos sao
    todos non-exportable em V1.
    """
    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse_adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {}
    node_map: dict[str, dict[str, Any]] = {}
    target_handle_map: dict[tuple[str, str], str | None] = {}

    for node in nodes:
        node_id = str(node["id"])
        node_map[node_id] = node
        in_degree[node_id] = 0

    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        target_handle = (
            edge.get("targetHandle") or edge.get("target_handle") or None
        )
        adjacency[source].append(target)
        reverse_adj[target].append(source)
        in_degree[target] = in_degree.get(target, 0) + 1
        target_handle_map[(source, target)] = target_handle

    return adjacency, reverse_adj, in_degree, node_map, target_handle_map


def topological_order(
    in_degree: dict[str, int],
    adjacency: dict[str, list[str]],
) -> list[str]:
    """Lista plana de node_ids em ordem topologica (BFS / Kahn).

    Levanta ``ValueError`` se houver ciclo — o runtime ja proibe ciclos,
    mas o exportador valida defensivamente para nao gerar SQL invalido.
    """
    remaining = dict(in_degree)
    queue = deque([nid for nid, deg in remaining.items() if deg == 0])
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for neighbor in adjacency.get(nid, []):
            remaining[neighbor] -= 1
            if remaining[neighbor] == 0:
                queue.append(neighbor)
    if len(order) != len(in_degree):
        raise ValueError("Workflow contem ciclo — exportacao impossivel.")
    return order


# ---------------------------------------------------------------------------
# Identificadores SQL — sanitizacao especifica do exportador
# ---------------------------------------------------------------------------

def sanitize_sql_identifier(value: str) -> str:
    """Normaliza ``node_id`` para uso como nome de tabela SQL.

    Mais permissivo que ``duckdb_storage.sanitize_name``: preserva caixa
    alta para legibilidade (o exportador vai citar os identificadores com
    aspas duplas, entao colisoes de case nao sao um problema).
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "node"


def quote_ident(value: str) -> str:
    """Escapa identificador para uso seguro em SQL DuckDB."""
    return '"' + value.replace('"', '""') + '"'


def sql_literal(value: Any) -> str:
    """Converte valor Python em literal SQL seguro (sem prepared statement)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    rendered = render_var_placeholders(text)
    escaped = rendered.replace("'", "''")
    return f"'{escaped}'"


def py_literal(value: Any) -> str:
    """Repr Python defensivo (lida com ``{{vars.X}}`` -> os.environ['X'])."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return repr(render_var_placeholders(value))
    return repr(value)


# ---------------------------------------------------------------------------
# Categorizacao de nos
# ---------------------------------------------------------------------------

# node_types suportados pelos exportadores SQL/Python na V1.
SUPPORTED_NODE_TYPES: frozenset[str] = frozenset({
    "sql_database",
    "inline_data",
    "filter",
    "mapper",
    "record_id",
    "sample",
    "sort",
    "join",
    "lookup",
    "aggregator",
    "deduplication",
    "union",
    "pivot",
    "unpivot",
    "text_to_rows",
    "loadNode",
})


def classify_node(node: dict[str, Any]) -> tuple[str, str | None]:
    """Retorna (status, reason). status in {"supported", "unsupported"}."""
    node_type = str(node.get("type") or "")
    if not node_type:
        return ("unsupported", "node sem 'type' definido")
    if node_type in SUPPORTED_NODE_TYPES:
        return ("supported", None)

    profile = NODE_EXECUTION_PROFILE.get(node_type)
    if profile is None:
        return ("unsupported", f"node_type '{node_type}' desconhecido")
    shape = profile["shape"]
    if shape == "control":
        return ("unsupported", "controle de fluxo nao e exportavel em V1")
    if shape == "io":
        return ("unsupported", f"entrada externa '{node_type}' nao suportada em V1")
    if shape == "output":
        return ("unsupported", f"saida externa '{node_type}' tem efeito colateral nao expressavel em SQL/Python")
    return ("unsupported", f"transformacao '{node_type}' nao suportada em V1")


# ---------------------------------------------------------------------------
# Auxiliares por handler
# ---------------------------------------------------------------------------

def get_handle_inputs(
    node_id: str,
    reverse_adj: dict[str, list[str]],
    target_handle_map: dict[tuple[str, str], str | None],
) -> dict[str, str]:
    """Retorna dicionario ``{handle_name: upstream_node_id}``.

    Quando o targetHandle e nulo, usa "default" como chave.
    """
    out: dict[str, str] = {}
    for upstream in reverse_adj.get(node_id, []):
        handle = target_handle_map.get((upstream, node_id)) or "default"
        out[handle] = upstream
    return out


def export_metadata(workflow_definition: dict[str, Any]) -> dict[str, Any]:
    """Metadados do workflow para o cabecalho dos exportadores."""
    return {
        "workflow_id": workflow_definition.get("id") or workflow_definition.get("workflow_id"),
        "workflow_name": workflow_definition.get("name") or workflow_definition.get("workflow_name"),
        "exported_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "shift_version": "1.0",
    }
