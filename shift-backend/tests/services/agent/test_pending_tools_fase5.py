"""
FASE 5 — testes das pending_* tools e suporte a temp_id no BuildSession.

Cobre:
  - test_pending_tools_registered: TOOL_REGISTRY contem todas as 5 tools
  - test_pending_add_node_rejects_duplicate_temp_id
  - test_pending_add_edge_unknown_source_temp_id: retorna erro estruturado
  - test_pending_add_edge_unknown_target_temp_id: retorna erro estruturado
  - test_pending_update_node_unknown_temp_id
  - test_pending_remove_node_clears_temp_id_map (nao, apenas verifica comportamento)
  - test_build_workflow_uses_new_format: _is_new_format detecta corretamente
  - test_plan_with_temp_ids_cross_reference: edges referenciam nos do mesmo plano
  - test_set_variables_applied_on_confirm
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.build_session_service import (
    BuildSession,
    BuildSessionService,
    build_session_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(workflow_id=None):
    return BuildSession(
        session_id=uuid.uuid4(),
        workflow_id=workflow_id or uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# test_pending_tools_registered
# ---------------------------------------------------------------------------

def test_pending_tools_registered():
    """Todas as 5 pending_* tools devem estar no TOOL_REGISTRY com is_pending=True."""
    from app.services.agent.tools.registry import TOOL_REGISTRY

    expected = {
        "pending_add_node",
        "pending_add_edge",
        "pending_update_node",
        "pending_remove_node",
        "pending_set_variables",
    }
    missing = expected - set(TOOL_REGISTRY.keys())
    assert not missing, f"Tools ausentes no TOOL_REGISTRY: {missing}"

    for name in expected:
        entry = TOOL_REGISTRY[name]
        assert entry.get("is_pending") is True, f"{name} deve ter is_pending=True"
        assert entry.get("requires_approval") is False, f"{name} nao deve exigir aprovacao"


# ---------------------------------------------------------------------------
# test_pending_add_node_rejects_duplicate_temp_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_add_node_rejects_duplicate_temp_id():
    """pending_add_node deve retornar erro JSON se temp_id ja foi usado na sessao."""
    import app.services.agent.tools.workflow_pending_tools as pt_module

    svc = BuildSessionService()
    session = _make_session()
    async with svc._lock:
        svc._sessions[str(session.session_id)] = session

    with patch.object(pt_module, "build_session_service", svc), \
         patch.object(pt_module, "async_session_factory"), \
         patch.object(pt_module.definition_event_service, "publish", new_callable=AsyncMock):

        # Primeira chamada — sucesso
        r1 = await pt_module.pending_add_node(
            db=None, ctx=None,
            session_id=str(session.session_id),
            temp_id="n_dup",
            node_type="filter",
            label="Filtro",
        )
        assert "error" not in json.loads(r1)

        # Segunda chamada com mesmo temp_id — deve retornar erro
        r2 = await pt_module.pending_add_node(
            db=None, ctx=None,
            session_id=str(session.session_id),
            temp_id="n_dup",
            node_type="mapper",
            label="Mapper",
        )
        result = json.loads(r2)
        assert "error" in result
        assert result["error"]["code"] == "DUPLICATE_TEMP_ID"


# ---------------------------------------------------------------------------
# test_pending_add_edge_unknown_temp_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_add_edge_unknown_source_temp_id():
    """pending_add_edge deve retornar UNKNOWN_TEMP_ID se source_temp_id nao existe."""
    import app.services.agent.tools.workflow_pending_tools as pt_module

    svc = BuildSessionService()
    session = _make_session()
    async with svc._lock:
        svc._sessions[str(session.session_id)] = session

    with patch.object(pt_module, "build_session_service", svc):
        result_json = await pt_module.pending_add_edge(
            db=None, ctx=None,
            session_id=str(session.session_id),
            source_temp_id="n_inexistente",
            target_temp_id="n_outro",
        )
    result = json.loads(result_json)
    assert "error" in result
    assert result["error"]["code"] == "UNKNOWN_TEMP_ID"
    assert result["error"]["details"]["field"] == "source_temp_id"


@pytest.mark.asyncio
async def test_pending_add_edge_unknown_target_temp_id():
    """pending_add_edge deve retornar UNKNOWN_TEMP_ID se target_temp_id nao existe."""
    import app.services.agent.tools.workflow_pending_tools as pt_module

    svc = BuildSessionService()
    session = _make_session()
    async with svc._lock:
        svc._sessions[str(session.session_id)] = session

    # Adiciona apenas o no de origem
    await svc.add_pending_node(
        session.session_id,
        node_type="filter",
        position={"x": 0, "y": 0},
        data={},
        temp_id="n_origem",
    )

    with patch.object(pt_module, "build_session_service", svc):
        result_json = await pt_module.pending_add_edge(
            db=None, ctx=None,
            session_id=str(session.session_id),
            source_temp_id="n_origem",
            target_temp_id="n_nao_existe",
        )
    result = json.loads(result_json)
    assert "error" in result
    assert result["error"]["code"] == "UNKNOWN_TEMP_ID"
    assert result["error"]["details"]["field"] == "target_temp_id"


# ---------------------------------------------------------------------------
# test_pending_update_node_unknown_temp_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_update_node_unknown_temp_id():
    """pending_update_node retorna UNKNOWN_TEMP_ID para temp_id inexistente."""
    import app.services.agent.tools.workflow_pending_tools as pt_module

    svc = BuildSessionService()
    session = _make_session()
    async with svc._lock:
        svc._sessions[str(session.session_id)] = session

    with patch.object(pt_module, "build_session_service", svc):
        result_json = await pt_module.pending_update_node(
            db=None, ctx=None,
            session_id=str(session.session_id),
            temp_id="n_fantasma",
            config_patch={"query": "SELECT 1"},
        )
    result = json.loads(result_json)
    assert "error" in result
    assert result["error"]["code"] == "UNKNOWN_TEMP_ID"


# ---------------------------------------------------------------------------
# test_build_workflow_uses_new_format
# ---------------------------------------------------------------------------

def test_is_new_format_detects_tool_key():
    """_is_new_format deve retornar True para ops com chave 'tool'."""
    from app.services.agent.graph.nodes.build_workflow import _is_new_format

    assert _is_new_format([{"tool": "pending_add_node", "arguments": {}}]) is True
    assert _is_new_format([{"op": "add_node"}]) is False
    assert _is_new_format([]) is False
    # Mix: qualquer op com "tool" e suficiente
    assert _is_new_format([{"op": "add_node"}, {"tool": "pending_add_node", "arguments": {}}]) is True


# ---------------------------------------------------------------------------
# test_plan_with_temp_ids_cross_reference
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_with_temp_ids_cross_reference():
    """Um plano com pending_add_edge referenciando temp_ids validos deve funcionar."""
    import app.services.agent.tools.workflow_pending_tools as pt_module

    svc = BuildSessionService()
    session = _make_session()
    async with svc._lock:
        svc._sessions[str(session.session_id)] = session

    with patch.object(pt_module, "build_session_service", svc), \
         patch.object(pt_module, "async_session_factory"), \
         patch.object(pt_module.definition_event_service, "publish", new_callable=AsyncMock):

        r_node1 = await pt_module.pending_add_node(
            db=None, ctx=None,
            session_id=str(session.session_id),
            temp_id="n_cleanup1",
            node_type="sql_script",
            label="Validacao",
        )
        r_node2 = await pt_module.pending_add_node(
            db=None, ctx=None,
            session_id=str(session.session_id),
            temp_id="n_cleanup2",
            node_type="sql_script",
            label="Normalizacao",
        )
        r_edge = await pt_module.pending_add_edge(
            db=None, ctx=None,
            session_id=str(session.session_id),
            source_temp_id="n_cleanup1",
            target_temp_id="n_cleanup2",
            source_handle="success",
        )

    d1 = json.loads(r_node1)
    d2 = json.loads(r_node2)
    de = json.loads(r_edge)

    assert "error" not in d1
    assert "error" not in d2
    assert "error" not in de
    assert de["source"] == d1["node_id"]
    assert de["target"] == d2["node_id"]


# ---------------------------------------------------------------------------
# test_set_variables_applied_on_confirm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_variables_applied_on_confirm():
    """Variaveis definidas via set_variables devem ser aplicadas no definition durante confirm."""
    from unittest.mock import MagicMock, AsyncMock, patch
    import copy

    wf_id = uuid.uuid4()
    session_id = uuid.uuid4()

    svc = BuildSessionService()
    sess = BuildSession(
        session_id=session_id,
        workflow_id=wf_id,
        created_at=datetime.now(timezone.utc),
        variables=[{"name": "env", "type": "string", "default": "prod"}],
    )
    async with svc._lock:
        svc._sessions[str(session_id)] = sess

    wf = MagicMock()
    wf.id = wf_id
    wf.definition = {"nodes": [], "edges": [], "variables": []}

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    import app.services.definition_event_service as des_module
    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock), \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock):

        result = await svc.confirm(session_id, db)

    # A definition do workflow deve ter sido atualizada com as variaveis
    applied_def = wf.definition
    assert applied_def["variables"] == [{"name": "env", "type": "string", "default": "prod"}]
    assert result.nodes_added == 0
    db.commit.assert_awaited_once()
