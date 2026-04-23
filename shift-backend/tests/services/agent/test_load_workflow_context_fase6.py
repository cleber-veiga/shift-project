"""
FASE 6 — testes do no load_workflow_context e injecao de workflow_state no planner.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.graph.nodes.load_workflow_context import load_workflow_context_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(intent: str, user_message: str) -> dict:
    return {
        "current_intent": {"intent": intent, "summary": ""},
        "messages": [{"role": "user", "content": user_message}],
        "user_context": {},
        "workflow_context": None,
        "thread_id": str(uuid.uuid4()),
    }


def _mock_db_with_wf(wf):
    mock_session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    mock_session.execute = AsyncMock(return_value=result_mock)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


# ---------------------------------------------------------------------------
# load_workflow_context_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_workflow_context_noop_for_build_workflow():
    """build_workflow nao deve carregar contexto — cria do zero."""
    wf_id = uuid.uuid4()
    state = _make_state("build_workflow", f"Crie um workflow {wf_id}")
    result = await load_workflow_context_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_load_workflow_context_noop_for_chat():
    """chat nao e intencao de edicao — sem carregamento."""
    state = _make_state("chat", "Ola, como vai?")
    result = await load_workflow_context_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_load_workflow_context_noop_when_no_uuid():
    """extend_workflow sem UUID na mensagem retorna {} sem query."""
    state = _make_state("extend_workflow", "adicione um filtro ao workflow principal")
    result = await load_workflow_context_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_load_workflow_context_for_extend_workflow():
    """extend_workflow com UUID valido carrega definicao do workflow."""
    wf_id = uuid.uuid4()
    mock_wf = MagicMock()
    mock_wf.name = "Fluxo de Teste"
    mock_wf.definition = {
        "nodes": [
            {"id": "n1", "type": "filter", "data": {"label": "Filtro Status"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "success"},
        ],
        "variables": [{"name": "env", "type": "string", "default": "prod"}],
    }

    state = _make_state("extend_workflow", f"adicione um mapper ao workflow {wf_id}")

    with patch(
        "app.services.agent.graph.nodes.load_workflow_context.async_session_factory",
        _mock_db_with_wf(mock_wf),
    ):
        result = await load_workflow_context_node(state)

    assert "workflow_context" in result
    ctx = result["workflow_context"]
    assert ctx["workflow_id"] == str(wf_id)
    assert ctx["name"] == "Fluxo de Teste"
    assert ctx["node_count"] == 1
    assert ctx["edge_count"] == 1
    assert ctx["nodes"][0]["label"] == "Filtro Status"
    assert ctx["edges"][0]["sourceHandle"] == "success"
    assert ctx["variables"] == [{"name": "env", "type": "string", "default": "prod"}]


@pytest.mark.asyncio
async def test_load_workflow_context_for_create_sub_workflow():
    """create_sub_workflow tambem deve carregar contexto."""
    wf_id = uuid.uuid4()
    mock_wf = MagicMock()
    mock_wf.name = "ETL Principal"
    mock_wf.definition = {"nodes": [], "edges": [], "variables": []}

    state = _make_state("create_sub_workflow", f"crie subfluxo de limpeza no workflow {wf_id}")

    with patch(
        "app.services.agent.graph.nodes.load_workflow_context.async_session_factory",
        _mock_db_with_wf(mock_wf),
    ):
        result = await load_workflow_context_node(state)

    assert "workflow_context" in result
    assert result["workflow_context"]["name"] == "ETL Principal"
    assert result["workflow_context"]["node_count"] == 0


@pytest.mark.asyncio
async def test_load_workflow_context_workflow_not_found():
    """Quando workflow nao existe, retorna {} sem levantar excecao."""
    wf_id = uuid.uuid4()
    state = _make_state("edit_workflow", f"altere o no sql no workflow {wf_id}")

    with patch(
        "app.services.agent.graph.nodes.load_workflow_context.async_session_factory",
        _mock_db_with_wf(None),
    ):
        result = await load_workflow_context_node(state)

    assert result == {}


@pytest.mark.asyncio
async def test_load_workflow_context_db_error_returns_empty():
    """Erro de banco deve retornar {} sem levantar excecao (silencioso)."""
    wf_id = uuid.uuid4()
    state = _make_state("extend_workflow", f"adicione filtro ao workflow {wf_id}")

    failing_factory = MagicMock(side_effect=RuntimeError("conn error"))

    with patch(
        "app.services.agent.graph.nodes.load_workflow_context.async_session_factory",
        failing_factory,
    ):
        result = await load_workflow_context_node(state)

    assert result == {}


# ---------------------------------------------------------------------------
# plan_actions._plan_build — injecao de workflow_state como XML
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_build_injects_workflow_state_xml():
    """_plan_build deve incluir <workflow_state> no payload quando workflow_context presente."""
    import app.services.agent.graph.nodes.plan_actions as pa_module
    from app.services.agent.graph.nodes.plan_actions import _plan_build

    wf_id = str(uuid.uuid4())
    state = {
        "messages": [{"role": "user", "content": f"adicione filtro ao workflow {wf_id}"}],
        "user_context": {},
        "workflow_context": {
            "workflow_id": wf_id,
            "name": "Teste",
            "node_count": 1,
            "edge_count": 0,
            "nodes": [{"id": "n1", "type": "filter", "label": "Filtro"}],
            "edges": [],
            "variables": [],
        },
        "thread_id": str(uuid.uuid4()),
    }

    captured: list[str] = []
    usage_mock = MagicMock()
    usage_mock.usage_entry.return_value = {"input_tokens": 10, "output_tokens": 5}

    async def fake_llm(system, user, fallback):
        captured.append(user)
        return {"workflow_id": wf_id, "ops": [], "summary": "test"}, usage_mock

    with patch.object(pa_module, "llm_complete_json_with_usage", side_effect=fake_llm):
        await _plan_build(state, {"intent": "extend_workflow", "summary": ""})

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert "workflow_state" in payload
    assert payload["workflow_state"].startswith("<workflow_state>")
    assert payload["workflow_state"].endswith("</workflow_state>")
    # Deve conter o conteudo do contexto
    inner = json.loads(payload["workflow_state"][len("<workflow_state>"):-len("</workflow_state>")])
    assert inner["workflow_id"] == wf_id
    # Nao deve duplicar como campo separado
    assert "workflow_context" not in payload


@pytest.mark.asyncio
async def test_plan_build_no_workflow_state_when_context_empty():
    """Sem workflow_context, payload nao deve ter workflow_state."""
    import app.services.agent.graph.nodes.plan_actions as pa_module
    from app.services.agent.graph.nodes.plan_actions import _plan_build

    wf_id = str(uuid.uuid4())
    state = {
        "messages": [{"role": "user", "content": f"crie workflow {wf_id}"}],
        "user_context": {},
        "workflow_context": None,
        "thread_id": str(uuid.uuid4()),
    }

    captured: list[str] = []
    usage_mock = MagicMock()
    usage_mock.usage_entry.return_value = {}

    async def fake_llm(system, user, fallback):
        captured.append(user)
        return {"workflow_id": wf_id, "ops": [], "summary": ""}, usage_mock

    with patch.object(pa_module, "llm_complete_json_with_usage", side_effect=fake_llm):
        await _plan_build(state, {"intent": "build_workflow", "summary": ""})

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert "workflow_state" not in payload
    assert "workflow_context" not in payload
