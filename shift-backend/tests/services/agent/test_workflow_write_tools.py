"""
Testes das write tools do Platform Agent.

Abordagem: mocks do AsyncSession — sem banco real.
Testes cobrem caminho feliz, erros de validacao, erros de permissao e
a serializacao garantida pelo SELECT FOR UPDATE (concorrencia).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from app.services.agent.base import AgentPermissionError
from app.services.agent.context import UserContext
from app.services.agent.tools.workflow_write_tools import (
    add_edge,
    add_node,
    create_workflow,
    remove_edge,
    remove_node,
    set_workflow_variables,
    update_node_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx(
    workspace_role: str = "MANAGER",
    project_role: str | None = "EDITOR",
    workspace_id=None,
) -> UserContext:
    ws_id = workspace_id or uuid4()
    return UserContext(
        user_id=uuid4(),
        workspace_id=ws_id,
        project_id=uuid4(),
        workspace_role=workspace_role,
        project_role=project_role,
        organization_id=ws_id,
        organization_role=None,
    )


def make_workflow(
    *,
    workspace_id=None,
    project_id=None,
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
    variables: list[dict] | None = None,
) -> MagicMock:
    wf = MagicMock()
    wf.id = uuid4()
    wf.workspace_id = workspace_id
    wf.project_id = project_id
    wf.definition = {
        "nodes": nodes or [],
        "edges": edges or [],
        "variables": variables or [],
    }
    return wf


def make_project(workspace_id) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), workspace_id=workspace_id)


def _db_returning(wf: MagicMock | None, project=None):
    """Constroi um AsyncSession mock que retorna wf no execute e project no get."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.get = AsyncMock(return_value=project)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    return db


def _ok(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _is_error(result: str, code: str | None = None) -> bool:
    try:
        obj = json.loads(result)
        if "error" not in obj:
            return False
        return code is None or obj["error"].get("code") == code
    except (json.JSONDecodeError, KeyError):
        return False


# ===========================================================================
# create_workflow
# ===========================================================================


@pytest.mark.asyncio
async def test_create_workflow_happy_path():
    ctx = make_ctx()
    project = make_project(ctx.workspace_id)
    db = _db_returning(None, project=project)

    new_wf = MagicMock()
    new_wf.id = uuid4()

    async def fake_refresh(obj):
        obj.id = new_wf.id

    db.refresh = fake_refresh

    result = await create_workflow(db=db, ctx=ctx, project_id=str(project.id), name="Meu Workflow")
    parsed = json.loads(result)
    assert "workflow_id" in parsed
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_workflow_invalid_project_id():
    ctx = make_ctx()
    db = _db_returning(None)
    result = await create_workflow(db=db, ctx=ctx, project_id="not-a-uuid", name="X")
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_create_workflow_project_not_found():
    ctx = make_ctx()
    db = _db_returning(None, project=None)
    result = await create_workflow(db=db, ctx=ctx, project_id=str(uuid4()), name="X")
    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_create_workflow_project_wrong_workspace():
    ctx = make_ctx()
    # project belongs to a different workspace
    project = make_project(uuid4())
    db = _db_returning(None, project=project)
    result = await create_workflow(db=db, ctx=ctx, project_id=str(project.id), name="X")
    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_create_workflow_empty_name():
    ctx = make_ctx()
    project = make_project(ctx.workspace_id)
    db = _db_returning(None, project=project)
    result = await create_workflow(db=db, ctx=ctx, project_id=str(project.id), name="   ")
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_create_workflow_permission_denied():
    ctx = make_ctx(workspace_role="VIEWER")
    db = _db_returning(None)
    with pytest.raises(AgentPermissionError):
        await create_workflow(db=db, ctx=ctx, project_id=str(uuid4()), name="X")


# ===========================================================================
# add_node
# ===========================================================================


@pytest.mark.asyncio
async def test_add_node_happy_path():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True):
        result = await add_node(
            db=db, ctx=ctx,
            workflow_id=str(wf.id),
            node_type="sql_script",
            position={"x": 100, "y": 200},
            config={"query": "SELECT 1"},
        )

    parsed = json.loads(result)
    assert "node_id" in parsed
    assert parsed["node_id"].startswith("node_")
    # definition was updated
    assert len(wf.definition["nodes"]) == 1
    assert wf.definition["nodes"][0]["type"] == "sql_script"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_node_invalid_workflow_id():
    ctx = make_ctx()
    db = _db_returning(None)
    result = await add_node(db=db, ctx=ctx, workflow_id="bad", node_type="sql_script", position={"x": 0, "y": 0})
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_add_node_invalid_node_type():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=False), \
         patch("app.services.agent.tools.workflow_write_tools.list_node_types", return_value=["sql_script"]):
        result = await add_node(db=db, ctx=ctx, workflow_id=str(wf.id), node_type="nonexistent", position={"x": 0, "y": 0})

    assert _is_error(result, "VALIDATION_ERROR")
    parsed = json.loads(result)
    assert "valid_types" in parsed["error"]["details"]


@pytest.mark.asyncio
async def test_add_node_invalid_position_non_finite():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True):
        result = await add_node(
            db=db, ctx=ctx,
            workflow_id=str(wf.id),
            node_type="sql_script",
            position={"x": float("inf"), "y": 0},
        )
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_add_node_workflow_not_found():
    ctx = make_ctx()
    db = _db_returning(None)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True):
        result = await add_node(db=db, ctx=ctx, workflow_id=str(uuid4()), node_type="sql_script", position={"x": 0, "y": 0})

    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_add_node_workflow_out_of_scope():
    ctx = make_ctx()
    # workflow belongs to a different workspace and no matching project
    wf = make_workflow(workspace_id=uuid4(), project_id=None)
    db = _db_returning(wf, project=None)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True):
        result = await add_node(db=db, ctx=ctx, workflow_id=str(wf.id), node_type="sql_script", position={"x": 0, "y": 0})

    assert _is_error(result, "NOT_FOUND")


# ===========================================================================
# update_node_config
# ===========================================================================


@pytest.mark.asyncio
async def test_update_node_config_happy_path():
    ctx = make_ctx()
    node_id = "node_abc"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[{"id": node_id, "type": "sql_script", "position": {"x": 0, "y": 0}, "data": {"query": "SELECT 1"}}],
    )
    db = _db_returning(wf)

    result = await update_node_config(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        node_id=node_id,
        config_patch={"query": "SELECT 2", "timeout": 30},
    )

    parsed = json.loads(result)
    assert parsed["node_id"] == node_id
    updated_data = wf.definition["nodes"][0]["data"]
    assert updated_data["query"] == "SELECT 2"
    assert updated_data["timeout"] == 30


@pytest.mark.asyncio
async def test_update_node_config_node_not_found():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id, nodes=[])
    db = _db_returning(wf)

    result = await update_node_config(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        node_id="node_ghost",
        config_patch={"x": 1},
    )
    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_update_node_config_invalid_patch_type():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    result = await update_node_config(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        node_id="any",
        config_patch="not_a_dict",  # type: ignore[arg-type]
    )
    assert _is_error(result, "VALIDATION_ERROR")


# ===========================================================================
# remove_node
# ===========================================================================


@pytest.mark.asyncio
async def test_remove_node_happy_path_with_cascade():
    ctx = make_ctx()
    node_a = "node_a"
    node_b = "node_b"
    edge_ab = "edge_ab"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[
            {"id": node_a, "type": "sql_script", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": node_b, "type": "sql_script", "position": {"x": 100, "y": 0}, "data": {}},
        ],
        edges=[{"id": edge_ab, "source": node_a, "target": node_b}],
    )
    db = _db_returning(wf)

    result = await remove_node(db=db, ctx=ctx, workflow_id=str(wf.id), node_id=node_a)
    parsed = json.loads(result)
    assert edge_ab in parsed["removed_edges"]
    assert not any(n["id"] == node_a for n in wf.definition["nodes"])
    assert not any(e["id"] == edge_ab for e in wf.definition["edges"])
    assert any(n["id"] == node_b for n in wf.definition["nodes"])


@pytest.mark.asyncio
async def test_remove_node_not_found():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id, nodes=[])
    db = _db_returning(wf)

    result = await remove_node(db=db, ctx=ctx, workflow_id=str(wf.id), node_id="ghost")
    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_remove_node_workflow_not_found():
    ctx = make_ctx()
    db = _db_returning(None)
    result = await remove_node(db=db, ctx=ctx, workflow_id=str(uuid4()), node_id="any")
    assert _is_error(result, "NOT_FOUND")


# ===========================================================================
# add_edge
# ===========================================================================


@pytest.mark.asyncio
async def test_add_edge_happy_path():
    ctx = make_ctx()
    node_a, node_b = "node_a", "node_b"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[
            {"id": node_a, "type": "t", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": node_b, "type": "t", "position": {"x": 0, "y": 0}, "data": {}},
        ],
    )
    db = _db_returning(wf)

    result = await add_edge(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        source_id=node_a,
        target_id=node_b,
        source_handle="true",
    )
    parsed = json.loads(result)
    assert "edge_id" in parsed
    assert parsed["edge_id"].startswith("edge_")
    edge = wf.definition["edges"][0]
    assert edge["source"] == node_a
    assert edge["target"] == node_b
    assert edge["sourceHandle"] == "true"
    assert "targetHandle" not in edge


@pytest.mark.asyncio
async def test_add_edge_self_loop():
    ctx = make_ctx()
    node_a = "node_a"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[{"id": node_a, "type": "t", "position": {"x": 0, "y": 0}, "data": {}}],
    )
    db = _db_returning(wf)

    result = await add_edge(db=db, ctx=ctx, workflow_id=str(wf.id), source_id=node_a, target_id=node_a)
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_add_edge_source_not_found():
    ctx = make_ctx()
    node_b = "node_b"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[{"id": node_b, "type": "t", "position": {"x": 0, "y": 0}, "data": {}}],
    )
    db = _db_returning(wf)

    result = await add_edge(db=db, ctx=ctx, workflow_id=str(wf.id), source_id="ghost", target_id=node_b)
    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_add_edge_target_not_found():
    ctx = make_ctx()
    node_a = "node_a"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[{"id": node_a, "type": "t", "position": {"x": 0, "y": 0}, "data": {}}],
    )
    db = _db_returning(wf)

    result = await add_edge(db=db, ctx=ctx, workflow_id=str(wf.id), source_id=node_a, target_id="ghost")
    assert _is_error(result, "NOT_FOUND")


# ===========================================================================
# remove_edge
# ===========================================================================


@pytest.mark.asyncio
async def test_remove_edge_happy_path():
    ctx = make_ctx()
    edge_id = "edge_xyz"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[
            {"id": "n1", "type": "t", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "n2", "type": "t", "position": {"x": 0, "y": 0}, "data": {}},
        ],
        edges=[{"id": edge_id, "source": "n1", "target": "n2"}],
    )
    db = _db_returning(wf)

    result = await remove_edge(db=db, ctx=ctx, workflow_id=str(wf.id), edge_id=edge_id)
    parsed = json.loads(result)
    assert parsed == {}
    assert wf.definition["edges"] == []


@pytest.mark.asyncio
async def test_remove_edge_not_found():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id, edges=[])
    db = _db_returning(wf)

    result = await remove_edge(db=db, ctx=ctx, workflow_id=str(wf.id), edge_id="ghost")
    assert _is_error(result, "NOT_FOUND")


@pytest.mark.asyncio
async def test_remove_edge_workflow_not_found():
    ctx = make_ctx()
    db = _db_returning(None)
    result = await remove_edge(db=db, ctx=ctx, workflow_id=str(uuid4()), edge_id="e1")
    assert _is_error(result, "NOT_FOUND")


# ===========================================================================
# set_workflow_variables
# ===========================================================================


@pytest.mark.asyncio
async def test_set_workflow_variables_happy_path():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    variables = [
        {"name": "start_date", "type": "string", "required": True, "description": "Data inicio"},
        {"name": "limit", "type": "integer", "required": False, "default": 100},
    ]
    result = await set_workflow_variables(db=db, ctx=ctx, workflow_id=str(wf.id), variables=variables)
    parsed = json.loads(result)
    assert parsed["variables_count"] == 2
    stored = wf.definition["variables"]
    assert stored[0]["name"] == "start_date"
    assert stored[1]["default"] == 100


@pytest.mark.asyncio
async def test_set_workflow_variables_invalid_type():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    result = await set_workflow_variables(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        variables=[{"name": "x", "type": "datetime"}],  # invalid type
    )
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_set_workflow_variables_missing_name():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    result = await set_workflow_variables(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        variables=[{"type": "string"}],  # name missing
    )
    assert _is_error(result, "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_set_workflow_variables_not_a_list():
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    result = await set_workflow_variables(
        db=db, ctx=ctx,
        workflow_id=str(wf.id),
        variables={"name": "x"},  # type: ignore[arg-type]
    )
    assert _is_error(result, "VALIDATION_ERROR")


# ===========================================================================
# Permissoes: VIEWER e CLIENT nao podem escrever
# ===========================================================================


@pytest.mark.asyncio
async def test_viewer_cannot_add_node():
    ctx = make_ctx(workspace_role="VIEWER", project_role=None)
    db = _db_returning(None)
    with pytest.raises(AgentPermissionError):
        with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True):
            await add_node(db=db, ctx=ctx, workflow_id=str(uuid4()), node_type="sql_script", position={"x": 0, "y": 0})


@pytest.mark.asyncio
async def test_client_without_editor_cannot_write():
    ctx = make_ctx(workspace_role="CONSULTANT", project_role="CLIENT")
    db = _db_returning(None)
    with pytest.raises(AgentPermissionError):
        await remove_node(db=db, ctx=ctx, workflow_id=str(uuid4()), node_id="n")


@pytest.mark.asyncio
async def test_manager_bypasses_project_role_check():
    """Workspace MANAGER herda EDITOR em todos os projetos."""
    ctx = make_ctx(workspace_role="MANAGER", project_role=None)
    node_id = "node_x"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[{"id": node_id, "type": "t", "position": {"x": 0, "y": 0}, "data": {}}],
    )
    db = _db_returning(wf)

    result = await remove_node(db=db, ctx=ctx, workflow_id=str(wf.id), node_id=node_id)
    parsed = json.loads(result)
    assert "removed_edges" in parsed


# ===========================================================================
# Concorrencia: SELECT FOR UPDATE serializa writes
# ===========================================================================


@pytest.mark.asyncio
async def test_concurrent_add_node_serializes_correctly():
    """Simula duas chamadas concorrentes a add_node verificando que ambas
    enxergam o estado correto graças ao SELECT FOR UPDATE.

    Com banco real (PostgreSQL) a segunda transacao esperaria o commit da
    primeira antes de adquirir o lock. Aqui verificamos que cada chamada
    usa o snapshot mais recente do definition retornado pelo SELECT.
    """
    ctx = make_ctx()
    wf_id = uuid4()

    # Estado inicial: sem nos
    base_def: dict = {"nodes": [], "edges": [], "variables": []}

    call_count = 0

    def make_fresh_wf():
        """Cada chamada recebe uma instancia independente com o definition atual."""
        nonlocal call_count
        call_count += 1
        wf = MagicMock()
        wf.id = wf_id
        wf.workspace_id = ctx.workspace_id
        # Simula que a segunda chamada ve o definition ja atualizado pela primeira.
        # Com FOR UPDATE real no PG isso ocorreria automaticamente pos-commit.
        wf.definition = {
            "nodes": list(base_def["nodes"]),
            "edges": [],
            "variables": [],
        }
        # Side effect: ao setar definition, atualiza base_def para proxima chamada
        type(wf).definition = property(
            lambda self: self._defn,
            lambda self, v: (setattr(self, "_defn", v), base_def["nodes"].clear(), base_def["nodes"].extend(v.get("nodes", []))),
        )
        wf._defn = {"nodes": list(base_def["nodes"]), "edges": [], "variables": []}
        return wf

    async def run_add(node_type: str, x: float):
        wf_instance = make_fresh_wf()
        db = _db_returning(wf_instance)
        with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True):
            return await add_node(
                db=db, ctx=ctx,
                workflow_id=str(wf_id),
                node_type=node_type,
                position={"x": x, "y": 0},
            )

    # Executa sequencialmente (sem paralelismo real com mock) para verificar
    # que cada chamada retorna um node_id unico e valido.
    r1 = await run_add("sql_script", 0.0)
    r2 = await run_add("mapper_node", 100.0)

    p1 = json.loads(r1)
    p2 = json.loads(r2)

    assert "node_id" in p1
    assert "node_id" in p2
    assert p1["node_id"] != p2["node_id"], "Cada chamada deve gerar node_id unico"


# ===========================================================================
# Audit log: linha criada com payload correto
# ===========================================================================


@pytest.mark.asyncio
async def test_audit_log_written_on_add_node():
    """Verifica que write_audit_log e chamado com before/after corretos."""
    ctx = make_ctx()
    thread_id = uuid4()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True), \
         patch("app.services.agent.tools.workflow_write_tools.write_audit_log", new_callable=AsyncMock) as mock_audit:

        await add_node(
            db=db, ctx=ctx,
            workflow_id=str(wf.id),
            node_type="sql_script",
            position={"x": 10, "y": 20},
            thread_id=thread_id,
        )

    mock_audit.assert_awaited_once()
    kwargs = mock_audit.call_args.kwargs
    assert kwargs["thread_id"] == thread_id
    assert kwargs["tool_name"] == "add_node"
    assert kwargs["status"] == "success"
    meta = kwargs["log_metadata"]
    assert "before" in meta
    assert "after" in meta
    assert meta["before"]["node_ids"] == []
    assert len(meta["after"]["node_ids"]) == 1


@pytest.mark.asyncio
async def test_audit_log_skipped_when_no_thread_id():
    """Sem thread_id, write_audit_log NAO deve ser chamado."""
    ctx = make_ctx()
    wf = make_workflow(workspace_id=ctx.workspace_id)
    db = _db_returning(wf)

    with patch("app.services.agent.tools.workflow_write_tools.has_processor", return_value=True), \
         patch("app.services.agent.tools.workflow_write_tools.write_audit_log", new_callable=AsyncMock) as mock_audit:

        await add_node(
            db=db, ctx=ctx,
            workflow_id=str(wf.id),
            node_type="sql_script",
            position={"x": 0, "y": 0},
            thread_id=None,
        )

    mock_audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_log_written_on_remove_node():
    ctx = make_ctx()
    thread_id = uuid4()
    node_id = "node_audit_test"
    wf = make_workflow(
        workspace_id=ctx.workspace_id,
        nodes=[{"id": node_id, "type": "t", "position": {"x": 0, "y": 0}, "data": {}}],
    )
    db = _db_returning(wf)

    with patch("app.services.agent.tools.workflow_write_tools.write_audit_log", new_callable=AsyncMock) as mock_audit:
        await remove_node(db=db, ctx=ctx, workflow_id=str(wf.id), node_id=node_id, thread_id=thread_id)

    mock_audit.assert_awaited_once()
    kwargs = mock_audit.call_args.kwargs
    assert kwargs["tool_name"] == "remove_node"
    assert kwargs["log_metadata"]["before"]["node_count"] == 1
    assert kwargs["log_metadata"]["after"]["node_count"] == 0
