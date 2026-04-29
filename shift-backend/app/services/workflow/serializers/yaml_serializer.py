"""
Serializador YAML — formato versionavel de workflows (Fase 9).

Formato:

    shift_version: "1.0"
    workflow_id: "..."
    workflow_name: "..."
    exported_at: "...Z"
    settings:
      variables: [...]
      schedule: null
    nodes:
      - id: "node_a"
        type: "filter"
        position: { x: 0, y: 0 }
        inputs: ["upstream_id"]
        outputs: ["downstream_id"]
        config: { ... }
    edges:
      - source: "a"
        target: "b"
        sourceHandle: null
        targetHandle: null

``inputs``/``outputs`` em cada node sao DERIVADOS das ``edges`` para tornar
o YAML mais legivel; ``from_yaml`` ignora esses campos e reconstroi a
WorkflowDefinition apenas a partir de ``edges`` + ``config`` (single source
of truth).

Round-trip preserva ``definition['nodes']`` e ``definition['edges']`` —
demais campos do workflow (name, description, status etc) ficam por conta
do chamador.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yaml


YAML_SCHEMA_VERSION = "1.0"


class YamlVersionError(Exception):
    """Erro estruturado para desencontros de versao do schema YAML."""

    def __init__(self, message: str, *, found: str | None, expected: str = YAML_SCHEMA_VERSION) -> None:
        self.found = found
        self.expected = expected
        super().__init__(message)


# ---------------------------------------------------------------------------
# Dump (workflow -> YAML)
# ---------------------------------------------------------------------------

def to_yaml(workflow_definition: dict[str, Any], *, name: str | None = None, workflow_id: str | None = None) -> str:
    """Serializa ``WorkflowDefinition`` em YAML versionado.

    ``workflow_definition`` e o ``Workflow.definition`` puro (campos
    ``nodes``, ``edges``, ``variables``, ``meta``). ``name`` e ``workflow_id``
    sao informados separadamente porque o ``Workflow`` model armazena esses
    campos fora de ``definition``.
    """
    nodes = workflow_definition.get("nodes") or []
    edges = workflow_definition.get("edges") or []

    inputs_by_target: dict[str, list[str]] = {}
    outputs_by_source: dict[str, list[str]] = {}
    for edge in edges:
        s = str(edge.get("source") or "")
        t = str(edge.get("target") or "")
        inputs_by_target.setdefault(t, []).append(s)
        outputs_by_source.setdefault(s, []).append(t)

    yaml_nodes: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        yaml_nodes.append({
            "id": node_id,
            "type": str(node.get("type") or ""),
            "position": dict(node.get("position") or {}),
            "inputs": list(inputs_by_target.get(node_id, [])),
            "outputs": list(outputs_by_source.get(node_id, [])),
            "config": dict(node.get("data") or {}),
        })

    yaml_edges: list[dict[str, Any]] = []
    for edge in edges:
        yaml_edges.append({
            "id": str(edge.get("id") or ""),
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "sourceHandle": edge.get("sourceHandle") or edge.get("source_handle"),
            "targetHandle": edge.get("targetHandle") or edge.get("target_handle"),
        })

    payload: dict[str, Any] = {
        "shift_version": YAML_SCHEMA_VERSION,
        "workflow_id": workflow_id or workflow_definition.get("workflow_id"),
        "workflow_name": name or workflow_definition.get("workflow_name") or workflow_definition.get("name"),
        "exported_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "settings": {
            "variables": list(workflow_definition.get("variables") or []),
            "schedule": workflow_definition.get("schedule"),
            "meta": dict(workflow_definition.get("meta") or {}) or None,
            "io_schema": workflow_definition.get("io_schema"),
        },
        "nodes": yaml_nodes,
        "edges": yaml_edges,
    }

    return yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )


# ---------------------------------------------------------------------------
# Load (YAML -> workflow)
# ---------------------------------------------------------------------------

def from_yaml(yaml_str: str) -> dict[str, Any]:
    """Deserializa YAML em ``WorkflowDefinition`` + metadados.

    Retorna ``{"definition": {...}, "name": str | None, "workflow_id": str | None}``.
    O chamador (endpoint /import) decide o que fazer com cada campo.
    """
    try:
        loaded = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML invalido: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ValueError("YAML invalido: esperado um documento mapeado no topo.")

    found_version = loaded.get("shift_version")
    _check_version(found_version)

    if "nodes" not in loaded or not isinstance(loaded["nodes"], list):
        raise ValueError("YAML invalido: campo 'nodes' obrigatorio (lista).")
    if "edges" not in loaded or not isinstance(loaded["edges"], list):
        raise ValueError("YAML invalido: campo 'edges' obrigatorio (lista).")

    nodes_out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in loaded["nodes"]:
        if not isinstance(raw, dict):
            raise ValueError("YAML invalido: cada item de 'nodes' deve ser um mapa.")
        node_id = str(raw.get("id") or "")
        ntype = str(raw.get("type") or "")
        if not node_id or not ntype:
            raise ValueError(f"YAML invalido: no sem id ou type ({raw!r}).")
        if node_id in seen_ids:
            raise ValueError(f"YAML invalido: id de no duplicado: '{node_id}'.")
        seen_ids.add(node_id)
        config = raw.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError(f"YAML invalido: 'config' do no '{node_id}' deve ser um mapa.")

        nodes_out.append({
            "id": node_id,
            "type": ntype,
            "position": dict(raw.get("position") or {"x": 0, "y": 0}),
            "data": dict(config),
        })

    edges_out: list[dict[str, Any]] = []
    for raw in loaded["edges"]:
        if not isinstance(raw, dict):
            raise ValueError("YAML invalido: cada item de 'edges' deve ser um mapa.")
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        if not source or not target:
            raise ValueError(f"YAML invalido: edge sem source ou target ({raw!r}).")
        edges_out.append({
            "id": str(raw.get("id") or f"{source}-{target}"),
            "source": source,
            "target": target,
            "sourceHandle": raw.get("sourceHandle"),
            "targetHandle": raw.get("targetHandle"),
        })

    settings = loaded.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}

    definition: dict[str, Any] = {
        "nodes": nodes_out,
        "edges": edges_out,
    }
    if settings.get("variables"):
        definition["variables"] = list(settings["variables"])
    if settings.get("schedule") is not None:
        definition["schedule"] = settings["schedule"]
    if settings.get("meta"):
        definition["meta"] = dict(settings["meta"])
    if settings.get("io_schema"):
        definition["io_schema"] = settings["io_schema"]

    return {
        "definition": definition,
        "name": loaded.get("workflow_name"),
        "workflow_id": loaded.get("workflow_id"),
    }


def _check_version(found: Any) -> None:
    """Aceita major-minor compativel; rejeita major divergente."""
    if found is None:
        raise YamlVersionError(
            "YAML invalido: 'shift_version' obrigatorio.",
            found=None,
        )
    found_str = str(found)
    expected_major = YAML_SCHEMA_VERSION.split(".", 1)[0]
    found_major = found_str.split(".", 1)[0]
    if found_major != expected_major:
        raise YamlVersionError(
            f"shift_version '{found_str}' incompativel "
            f"(esperado major '{expected_major}').",
            found=found_str,
        )
    # diferenca minor passa silenciosa — frontend pode logar warning se quiser.
