"""
Tools de escrita do Platform Agent: criacao e modificacao de definicoes de workflow.

Todas as funcoes:
- Requerem workspace CONSULTANT + project EDITOR (mutations destrutivas).
- Usam SELECT FOR UPDATE para serializar writes concorrentes na mesma linha.
- Retornam JSON string em caso de sucesso OU {"error": {"code","message","details"}}.
- Gravam linha em agent_audit_log com before/after do trecho JSONB afetado
  quando thread_id e fornecido (omitido em testes unitarios).
"""

from __future__ import annotations

import copy
import json
import math
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Workflow
from app.services.agent.base import (
    require_project_role,
    require_workspace_role,
    sanitize_llm_string,
)
from app.services.agent.context import UserContext
from app.services.agent.persistence import write_audit_log
from app.services.workflow.nodes import has_processor, list_node_types

# ---------------------------------------------------------------------------
# Tipos validos de variavel de workflow
# ---------------------------------------------------------------------------

_VALID_VAR_TYPES = frozenset({"string", "number", "integer", "boolean", "object", "array"})

# ---------------------------------------------------------------------------
# Helpers de resposta estruturada
# ---------------------------------------------------------------------------


def _ok(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(code: str, message: str, details: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return json.dumps({"error": payload}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Validadores
# ---------------------------------------------------------------------------


def _validate_position(position: Any) -> str | None:
    """Retorna mensagem de erro ou None se valido."""
    if not isinstance(position, dict):
        return "position deve ser um objeto com chaves x e y."
    x, y = position.get("x"), position.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return "position.x e position.y devem ser numeros."
    if not (math.isfinite(x) and math.isfinite(y)):
        return "position.x e position.y devem ser numeros finitos (sem Inf/NaN)."
    return None


def _validate_variable(v: Any) -> str | None:
    """Retorna mensagem de erro ou None se valido."""
    if not isinstance(v, dict):
        return "cada variavel deve ser um objeto JSON."
    name = v.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        return "variavel.name e obrigatorio e deve ser uma string nao-vazia."
    vtype = v.get("type")
    if vtype not in _VALID_VAR_TYPES:
        return (
            f"variavel.type '{vtype}' invalido. "
            f"Valores aceitos: {sorted(_VALID_VAR_TYPES)}"
        )
    return None


# ---------------------------------------------------------------------------
# Helpers internos: escopo e locking
# ---------------------------------------------------------------------------


async def _load_workflow_locked(
    db: AsyncSession,
    workflow_id: UUID,
    ctx: UserContext,
) -> Workflow | None:
    """Carrega o workflow com SELECT FOR UPDATE.

    Serializa mutations concorrentes: a segunda transacao espera o commit
    da primeira antes de adquirir o lock e ler a definicao atualizada.
    Retorna None se o workflow nao existir ou estiver fora do escopo do usuario.
    """
    from app.models.project import Project

    stmt = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .with_for_update()
    )
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if wf is None:
        return None

    # Verifica escopo: workspace direto OU via projeto
    if wf.workspace_id == ctx.workspace_id:
        return wf
    if wf.project_id is not None:
        proj = await db.get(Project, wf.project_id)
        if proj is not None and proj.workspace_id == ctx.workspace_id:
            return wf
    return None


def _defn(wf: Workflow) -> dict[str, Any]:
    """Copia profunda da definicao do workflow para mutacao segura."""
    d = wf.definition if isinstance(wf.definition, dict) else {}
    return copy.deepcopy(d)


# ---------------------------------------------------------------------------
# Helper de auditoria
# ---------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    ctx: UserContext,
    thread_id: UUID | None,
    tool_name: str,
    arguments: dict[str, Any],
    before: Any,
    after: Any,
) -> None:
    """Grava before/after em agent_audit_log. No-op quando thread_id e None."""
    if thread_id is None:
        return
    await write_audit_log(
        db,
        thread_id=thread_id,
        user_id=ctx.user_id,
        tool_name=tool_name,
        tool_arguments=arguments,
        status="success",
        log_metadata={"before": before, "after": after},
    )


# ---------------------------------------------------------------------------
# Tools publicas
# ---------------------------------------------------------------------------


async def create_workflow(
    *,
    db: AsyncSession,
    ctx: UserContext,
    project_id: str,
    name: str,
    description: str | None = None,
    thread_id: UUID | None = None,
) -> str:
    """Cria um workflow vazio (draft) em um projeto.

    Retorna: {"workflow_id": "<uuid>"}
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        pid = UUID(project_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"project_id invalido: '{project_id}'")

    name = sanitize_llm_string(name.strip()) if name else ""
    if not name:
        return _err("VALIDATION_ERROR", "name nao pode ser vazio.")
    if len(name) > 255:
        return _err("VALIDATION_ERROR", "name excede 255 caracteres.")

    clean_desc: str | None = None
    if description:
        clean_desc = sanitize_llm_string(description.strip()) or None

    from app.models.project import Project

    proj = await db.get(Project, pid)
    if proj is None or proj.workspace_id != ctx.workspace_id:
        return _err("NOT_FOUND", f"Projeto '{project_id}' nao encontrado.")

    wf = Workflow(
        name=name,
        description=clean_desc,
        project_id=pid,
        workspace_id=proj.workspace_id,
        is_template=False,
        is_published=False,
        status="draft",
        definition={"nodes": [], "edges": [], "variables": []},
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    await db.commit()

    result = {"workflow_id": str(wf.id)}
    await _audit(
        db, ctx, thread_id, "create_workflow",
        {"project_id": project_id, "name": name},
        None,
        result,
    )
    return _ok(result)


async def add_node(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    node_type: str,
    position: dict[str, Any],
    config: dict[str, Any] | None = None,
    thread_id: UUID | None = None,
) -> str:
    """Adiciona um novo no ao workflow.

    Retorna: {"node_id": "<id gerado>"}
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        wid = UUID(workflow_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"workflow_id invalido: '{workflow_id}'")

    if not has_processor(node_type):
        return _err(
            "VALIDATION_ERROR",
            f"node_type '{node_type}' nao existe no registry.",
            {"valid_types": list_node_types()},
        )

    pos_err = _validate_position(position)
    if pos_err:
        return _err("VALIDATION_ERROR", pos_err)

    wf = await _load_workflow_locked(db, wid, ctx)
    if wf is None:
        return _err("NOT_FOUND", f"Workflow '{workflow_id}' nao encontrado.")

    definition = _defn(wf)
    nodes: list[dict[str, Any]] = list(definition.get("nodes") or [])
    before_ids = [n["id"] for n in nodes]

    node_id = f"node_{uuid.uuid4().hex[:12]}"
    nodes.append({
        "id": node_id,
        "type": node_type,
        "position": {"x": float(position["x"]), "y": float(position["y"])},
        "data": config or {},
    })
    definition["nodes"] = nodes
    wf.definition = definition
    await db.flush()
    await db.commit()

    result = {"node_id": node_id}
    await _audit(
        db, ctx, thread_id, "add_node",
        {"workflow_id": workflow_id, "node_type": node_type},
        {"node_ids": before_ids},
        {"node_ids": [n["id"] for n in nodes]},
    )
    return _ok(result)


async def update_node_config(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    node_id: str,
    config_patch: dict[str, Any],
    thread_id: UUID | None = None,
) -> str:
    """Atualiza parcialmente o campo `data` de um no existente (merge shallow).

    Retorna: {"node_id": "<node_id>"}
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        wid = UUID(workflow_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"workflow_id invalido: '{workflow_id}'")

    if not isinstance(config_patch, dict):
        return _err("VALIDATION_ERROR", "config_patch deve ser um objeto JSON.")

    wf = await _load_workflow_locked(db, wid, ctx)
    if wf is None:
        return _err("NOT_FOUND", f"Workflow '{workflow_id}' nao encontrado.")

    definition = _defn(wf)
    nodes: list[dict[str, Any]] = list(definition.get("nodes") or [])

    idx = next((i for i, n in enumerate(nodes) if n["id"] == node_id), None)
    if idx is None:
        return _err("NOT_FOUND", f"No '{node_id}' nao encontrado no workflow.")

    before_data = copy.deepcopy(nodes[idx].get("data") or {})
    nodes[idx]["data"] = {**before_data, **config_patch}

    definition["nodes"] = nodes
    wf.definition = definition
    await db.flush()
    await db.commit()

    result = {"node_id": node_id}
    await _audit(
        db, ctx, thread_id, "update_node_config",
        {"workflow_id": workflow_id, "node_id": node_id},
        {"data": before_data},
        {"data": nodes[idx]["data"]},
    )
    return _ok(result)


async def remove_node(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    node_id: str,
    thread_id: UUID | None = None,
) -> str:
    """Remove um no e todas as arestas conectadas a ele.

    Retorna: {"removed_edges": ["<edge_id>", ...]}
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        wid = UUID(workflow_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"workflow_id invalido: '{workflow_id}'")

    wf = await _load_workflow_locked(db, wid, ctx)
    if wf is None:
        return _err("NOT_FOUND", f"Workflow '{workflow_id}' nao encontrado.")

    definition = _defn(wf)
    nodes: list[dict[str, Any]] = list(definition.get("nodes") or [])
    edges: list[dict[str, Any]] = list(definition.get("edges") or [])

    if not any(n["id"] == node_id for n in nodes):
        return _err("NOT_FOUND", f"No '{node_id}' nao encontrado no workflow.")

    removed_edges = [
        e["id"]
        for e in edges
        if e.get("source") == node_id or e.get("target") == node_id
    ]
    before = {"node_count": len(nodes), "edge_count": len(edges)}

    nodes = [n for n in nodes if n["id"] != node_id]
    edges = [e for e in edges if e["id"] not in set(removed_edges)]

    definition["nodes"] = nodes
    definition["edges"] = edges
    wf.definition = definition
    await db.flush()
    await db.commit()

    result = {"removed_edges": removed_edges}
    await _audit(
        db, ctx, thread_id, "remove_node",
        {"workflow_id": workflow_id, "node_id": node_id},
        before,
        {"node_count": len(nodes), "edge_count": len(edges)},
    )
    return _ok(result)


async def add_edge(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    source_id: str,
    target_id: str,
    source_handle: str | None = None,
    target_handle: str | None = None,
    thread_id: UUID | None = None,
) -> str:
    """Adiciona uma aresta entre dois nos existentes.

    Retorna: {"edge_id": "<id gerado>"}
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        wid = UUID(workflow_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"workflow_id invalido: '{workflow_id}'")

    if source_id == target_id:
        return _err("VALIDATION_ERROR", "Aresta nao pode conectar um no a si mesmo.")

    wf = await _load_workflow_locked(db, wid, ctx)
    if wf is None:
        return _err("NOT_FOUND", f"Workflow '{workflow_id}' nao encontrado.")

    definition = _defn(wf)
    nodes: list[dict[str, Any]] = list(definition.get("nodes") or [])
    node_ids = {n["id"] for n in nodes}

    if source_id not in node_ids:
        return _err("NOT_FOUND", f"No fonte '{source_id}' nao existe no workflow.")
    if target_id not in node_ids:
        return _err("NOT_FOUND", f"No destino '{target_id}' nao existe no workflow.")

    edges: list[dict[str, Any]] = list(definition.get("edges") or [])
    edge_id = f"edge_{uuid.uuid4().hex[:12]}"
    edge: dict[str, Any] = {"id": edge_id, "source": source_id, "target": target_id}
    if source_handle is not None:
        edge["sourceHandle"] = source_handle
    if target_handle is not None:
        edge["targetHandle"] = target_handle

    edges.append(edge)
    definition["edges"] = edges
    wf.definition = definition
    await db.flush()
    await db.commit()

    result = {"edge_id": edge_id}
    await _audit(
        db, ctx, thread_id, "add_edge",
        {"workflow_id": workflow_id, "source_id": source_id, "target_id": target_id},
        {"edge_count": len(edges) - 1},
        {"edge_count": len(edges)},
    )
    return _ok(result)


async def remove_edge(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    edge_id: str,
    thread_id: UUID | None = None,
) -> str:
    """Remove uma aresta do workflow.

    Retorna: {} em caso de sucesso.
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        wid = UUID(workflow_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"workflow_id invalido: '{workflow_id}'")

    wf = await _load_workflow_locked(db, wid, ctx)
    if wf is None:
        return _err("NOT_FOUND", f"Workflow '{workflow_id}' nao encontrado.")

    definition = _defn(wf)
    edges: list[dict[str, Any]] = list(definition.get("edges") or [])

    if not any(e["id"] == edge_id for e in edges):
        return _err("NOT_FOUND", f"Aresta '{edge_id}' nao encontrada no workflow.")

    before_count = len(edges)
    edges = [e for e in edges if e["id"] != edge_id]
    definition["edges"] = edges
    wf.definition = definition
    await db.flush()
    await db.commit()

    await _audit(
        db, ctx, thread_id, "remove_edge",
        {"workflow_id": workflow_id, "edge_id": edge_id},
        {"edge_count": before_count},
        {"edge_count": len(edges)},
    )
    return _ok({})


async def set_workflow_variables(
    *,
    db: AsyncSession,
    ctx: UserContext,
    workflow_id: str,
    variables: list[dict[str, Any]],
    thread_id: UUID | None = None,
) -> str:
    """Substitui integralmente a lista de variaveis do workflow.

    Retorna: {"variables_count": <int>}
    """
    require_workspace_role(ctx, "CONSULTANT")
    require_project_role(ctx, "EDITOR")

    try:
        wid = UUID(workflow_id)
    except ValueError:
        return _err("VALIDATION_ERROR", f"workflow_id invalido: '{workflow_id}'")

    if not isinstance(variables, list):
        return _err("VALIDATION_ERROR", "variables deve ser uma lista de objetos.")

    for i, v in enumerate(variables):
        err = _validate_variable(v)
        if err:
            return _err("VALIDATION_ERROR", f"variables[{i}]: {err}")

    # Normaliza: guarda apenas os campos conhecidos
    clean_vars: list[dict[str, Any]] = [
        {
            "name": v["name"].strip(),
            "type": v["type"],
            "required": bool(v.get("required", False)),
            "default": v.get("default"),
            "description": str(v.get("description") or ""),
        }
        for v in variables
    ]

    wf = await _load_workflow_locked(db, wid, ctx)
    if wf is None:
        return _err("NOT_FOUND", f"Workflow '{workflow_id}' nao encontrado.")

    definition = _defn(wf)
    before_vars = copy.deepcopy(definition.get("variables") or [])
    definition["variables"] = clean_vars
    wf.definition = definition
    await db.flush()
    await db.commit()

    result = {"variables_count": len(clean_vars)}
    await _audit(
        db, ctx, thread_id, "set_workflow_variables",
        {"workflow_id": workflow_id, "variables_count": len(clean_vars)},
        {"variables": before_vars},
        {"variables": clean_vars},
    )
    return _ok(result)
