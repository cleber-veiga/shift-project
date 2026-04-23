"""
Testes do no build_workflow e do planner de build (FASE 4/5).

Cobre:
  - compute_layout: layout correto para cadeia linear e grafo com bifurcacao
  - _plan_build: retorna build_plan quando workflow_id presente
  - _plan_build: retorna clarification_question quando workflow_id ausente
  - build_workflow_node: recusa ops > 50
  - build_workflow_node: recusa SQL destrutivo
  - build_workflow_node: budget check bloqueia usuario acima do limite
  - build_workflow_node: fluxo completo (confirm) com DB mock
  - build_workflow_node: fluxo completo (cancel)
  - _after_plan: roteia para build_workflow quando build_plan presente
  - understand_intent_node: aceita intencoes de build
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.agent.graph.builder import _after_plan
from app.services.agent.graph.llm import LLMResponse
from app.services.agent.graph.nodes.build_workflow import build_workflow_node
from app.services.agent.graph.nodes.plan_actions import plan_actions_node, _BUILD_INTENTS
from app.services.agent.graph.nodes.understand_intent import understand_intent_node, _VALID
from app.services.agent.layout import compute_layout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_usage(model: str = "test-model") -> LLMResponse:
    return LLMResponse(content="", prompt_tokens=0, completion_tokens=0, model=model)


def _json_mock(payload: dict) -> AsyncMock:
    return AsyncMock(return_value=(payload, _fake_usage()))


def _make_state(**kwargs) -> dict:
    return {
        "thread_id": str(uuid4()),
        "user_context": {
            "user_id": str(uuid4()),
            "workspace_id": str(uuid4()),
        },
        "messages": [{"role": "user", "content": "teste"}],
        **kwargs,
    }


def _mock_async_session_factory():
    """Returns a factory that produces a mock async context manager (async with ...)."""
    mock_db = AsyncMock()

    @asynccontextmanager
    async def _factory():
        yield mock_db

    factory = MagicMock(side_effect=_factory)
    return factory, mock_db


def _mock_publish_recording() -> tuple[AsyncMock, list[str]]:
    """Returns (publish_mock, events_list). publish_mock records event_type calls."""
    events: list[str] = []

    async def _side_effect(db, *, workflow_id, event_type, payload, client_mutation_id=None):
        events.append(event_type)

    mock = AsyncMock(side_effect=_side_effect)
    return mock, events


def _mock_build_session(session_id=None):
    sid = session_id or uuid4()
    session = MagicMock()
    session.session_id = sid
    return session


# ---------------------------------------------------------------------------
# compute_layout
# ---------------------------------------------------------------------------


class TestComputeLayout:
    def test_empty_returns_empty(self):
        assert compute_layout([], []) == []

    def test_single_node_gets_offset(self):
        positions = compute_layout([{"label": "A", "node_type": "filter"}], [])
        assert len(positions) == 1
        assert positions[0]["x"] == 120.0
        assert positions[0]["y"] == 120.0

    def test_linear_chain_x_increases(self):
        nodes = [
            {"label": "A", "node_type": "filter"},
            {"label": "B", "node_type": "mapper"},
            {"label": "C", "node_type": "bulk_insert"},
        ]
        edges = [
            {"source_label": "A", "target_label": "B"},
            {"source_label": "B", "target_label": "C"},
        ]
        positions = compute_layout(nodes, edges)
        assert len(positions) == 3
        assert positions[0]["x"] < positions[1]["x"] < positions[2]["x"]

    def test_parallel_nodes_same_x(self):
        nodes = [
            {"label": "Inicio", "node_type": "filter"},
            {"label": "Esq", "node_type": "mapper"},
            {"label": "Dir", "node_type": "bulk_insert"},
        ]
        edges = [
            {"source_label": "Inicio", "target_label": "Esq"},
            {"source_label": "Inicio", "target_label": "Dir"},
        ]
        positions = compute_layout(nodes, edges)
        assert positions[1]["x"] == positions[2]["x"]
        assert positions[1]["y"] != positions[2]["y"]

    def test_unknown_edge_labels_ignored(self):
        nodes = [{"label": "A", "node_type": "filter"}]
        edges = [{"source_label": "X", "target_label": "Y"}]
        positions = compute_layout(nodes, edges)
        assert len(positions) == 1


# ---------------------------------------------------------------------------
# understand_intent_node — build intents
# ---------------------------------------------------------------------------


class TestUnderstandIntentBuildIntents:
    def test_build_intents_in_valid_set(self):
        for intent in ("build_workflow", "extend_workflow", "edit_workflow", "create_sub_workflow"):
            assert intent in _VALID

    @pytest.mark.asyncio
    async def test_extend_workflow_classified_correctly(self):
        with patch(
            "app.services.agent.graph.nodes.understand_intent.llm_complete_json_with_usage",
            _json_mock({"intent": "extend_workflow", "summary": "adicionar nos"}),
        ):
            state = _make_state()
            result = await understand_intent_node(state)
            assert result["current_intent"]["intent"] == "extend_workflow"

    @pytest.mark.asyncio
    async def test_invalid_build_intent_falls_back_to_chat(self):
        with patch(
            "app.services.agent.graph.nodes.understand_intent.llm_complete_json_with_usage",
            _json_mock({"intent": "build_everything", "summary": "teste"}),
        ):
            state = _make_state()
            result = await understand_intent_node(state)
            assert result["current_intent"]["intent"] == "chat"


# ---------------------------------------------------------------------------
# _after_plan router
# ---------------------------------------------------------------------------


class TestAfterPlanRouter:
    def test_routes_to_build_workflow_when_build_plan_present(self):
        state = {"build_plan": {"workflow_id": str(uuid4()), "ops": []}}
        assert _after_plan(state) == "build_workflow"

    def test_routes_to_report_when_no_workflow_id(self):
        state = {"build_plan": {"workflow_id": None, "ops": []}}
        assert _after_plan(state) == "report"

    def test_routes_to_human_approval_with_actions(self):
        state = {"build_plan": None, "proposed_actions": [{"tool": "x"}]}
        assert _after_plan(state) == "human_approval"

    def test_routes_to_report_with_no_actions_and_no_plan(self):
        state = {"build_plan": None, "proposed_actions": []}
        assert _after_plan(state) == "report"


# ---------------------------------------------------------------------------
# plan_actions_node — build path
# ---------------------------------------------------------------------------


class TestPlanActionsBuildPath:
    @pytest.mark.asyncio
    async def test_build_intent_returns_build_plan(self):
        wf_id = str(uuid4())
        with (
            patch(
                "app.services.agent.graph.nodes.plan_actions._check_soft_cap",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.agent.graph.nodes.plan_actions.llm_complete_json_with_usage",
                _json_mock(
                    {
                        "workflow_id": wf_id,
                        "ops": [
                            {"op": "add_node", "node_type": "filter", "label": "Filtro", "config": {}},
                        ],
                        "summary": "Adicionar filtro",
                    }
                ),
            ),
        ):
            state = _make_state(
                current_intent={"intent": "extend_workflow", "summary": "adicionar filtro"}
            )
            result = await plan_actions_node(state)
            assert result["build_plan"]["workflow_id"] == wf_id
            assert len(result["build_plan"]["ops"]) == 1
            assert result["proposed_actions"] == []

    @pytest.mark.asyncio
    async def test_build_intent_without_workflow_id_returns_clarification(self):
        with (
            patch(
                "app.services.agent.graph.nodes.plan_actions._check_soft_cap",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.agent.graph.nodes.plan_actions.llm_complete_json_with_usage",
                _json_mock({"workflow_id": None, "ops": [], "summary": ""}),
            ),
        ):
            state = _make_state(
                current_intent={"intent": "build_workflow", "summary": "criar workflow"}
            )
            result = await plan_actions_node(state)
            assert result.get("build_plan") is None
            assert result.get("clarification_question")
            assert result["proposed_actions"] == []


# ---------------------------------------------------------------------------
# build_workflow_node
# ---------------------------------------------------------------------------

# Common patches for tests that don't reach the DB layer (early-exit guardrails)
_EARLY_EXIT_PATCHES = [
    "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
]


class TestBuildWorkflowNode:
    @pytest.mark.asyncio
    async def test_missing_workflow_id_returns_error(self):
        state = _make_state(build_plan={"workflow_id": None, "ops": [], "summary": ""})
        result = await build_workflow_node(state)
        assert "final_report" in result
        assert result.get("build_session_id") is None

    @pytest.mark.asyncio
    async def test_invalid_workflow_id_returns_error(self):
        state = _make_state(build_plan={"workflow_id": "not-a-uuid", "ops": [], "summary": ""})
        result = await build_workflow_node(state)
        assert "final_report" in result

    @pytest.mark.asyncio
    async def test_ops_budget_exceeded(self):
        ops = [{"op": "add_node", "node_type": "filter", "label": f"N{i}", "config": {}} for i in range(51)]
        state = _make_state(build_plan={"workflow_id": str(uuid4()), "ops": ops, "summary": ""})
        with patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
            return_value=(True, None),
        ):
            result = await build_workflow_node(state)
        assert "guardrails_violation" in result
        assert "50" in result["guardrails_violation"]

    @pytest.mark.asyncio
    async def test_destructive_sql_blocked(self):
        wf_id = str(uuid4())
        ops = [{"op": "add_node", "node_type": "sql_script", "label": "Bad SQL",
                "config": {"query": "DELETE FROM orders WHERE id > 0"}}]
        state = _make_state(build_plan={"workflow_id": wf_id, "ops": ops, "summary": ""})
        with patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
            return_value=(True, None),
        ), patch(
            "app.services.agent.graph.nodes.build_workflow.interrupt",
            return_value={"approved": False},
        ):
            result = await build_workflow_node(state)
        assert "guardrails_violation" in result
        assert "destrutivo" in result["guardrails_violation"].lower()

    @pytest.mark.asyncio
    async def test_truncate_sql_blocked(self):
        wf_id = str(uuid4())
        ops = [{"op": "add_node", "node_type": "sql_script", "label": "Trunc",
                "config": {"query": "TRUNCATE TABLE staging"}}]
        state = _make_state(build_plan={"workflow_id": wf_id, "ops": ops, "summary": ""})
        with patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
            return_value=(True, None),
        ), patch(
            "app.services.agent.graph.nodes.build_workflow.interrupt",
            return_value={"approved": False},
        ):
            result = await build_workflow_node(state)
        assert "guardrails_violation" in result

    @pytest.mark.asyncio
    async def test_budget_check_blocks_user(self):
        wf_id = str(uuid4())
        state = _make_state(build_plan={"workflow_id": wf_id, "ops": [], "summary": ""})
        with patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
            return_value=(False, "Limite de 50 build sessions/dia atingido."),
        ):
            result = await build_workflow_node(state)
        assert "guardrails_violation" in result
        assert "Limite" in result["final_report"]

    @pytest.mark.asyncio
    async def test_confirm_flow_publishes_events_and_reports(self):
        wf_id = str(uuid4())
        session_id = uuid4()
        ops = [
            {"op": "add_node", "node_type": "filter", "label": "Filtro", "config": {}},
            {"op": "add_node", "node_type": "mapper", "label": "Mapper", "config": {}},
            {"op": "add_edge", "source_label": "Filtro", "target_label": "Mapper", "source_handle": "success"},
        ]
        state = _make_state(build_plan={"workflow_id": wf_id, "ops": ops, "summary": "Teste"})

        mock_session = _mock_build_session(session_id)
        mock_node1 = MagicMock()
        mock_node1.node_id = f"node_{uuid4().hex[:12]}"
        mock_node1.to_dict = MagicMock(return_value={"id": mock_node1.node_id, "type": "filter", "data": {}})
        mock_node2 = MagicMock()
        mock_node2.node_id = f"node_{uuid4().hex[:12]}"
        mock_node2.to_dict = MagicMock(return_value={"id": mock_node2.node_id, "type": "mapper", "data": {}})
        mock_edge = MagicMock()
        mock_edge.to_dict = MagicMock(return_value={"id": "edge_abc", "source": mock_node1.node_id, "target": mock_node2.node_id})

        publish_mock, published_events = _mock_publish_recording()
        factory, _ = _mock_async_session_factory()

        with (
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget", return_value=(True, None)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.create", AsyncMock(return_value=mock_session)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_node", AsyncMock(side_effect=[mock_node1, mock_node2])),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_edge", AsyncMock(return_value=mock_edge)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.set_audit", AsyncMock()),
            patch("app.services.agent.graph.nodes.build_workflow.async_session_factory", factory),
            patch("app.services.agent.graph.nodes.build_workflow.definition_event_service.publish", publish_mock),
            patch("app.services.agent.graph.nodes.build_workflow.interrupt", return_value={"action": "confirm"}),
            patch("app.services.agent.graph.nodes.build_workflow._write_audit", AsyncMock()),
        ):
            result = await build_workflow_node(state)

        assert result["build_session_id"] == str(session_id)
        assert "final_report" in result
        assert "build_started" in published_events
        assert "pending_node_added" in published_events
        assert "pending_edge_added" in published_events
        assert "build_ready" in published_events
        assert "build_cancelled" not in published_events

    @pytest.mark.asyncio
    async def test_cancel_flow_publishes_build_cancelled(self):
        wf_id = str(uuid4())
        session_id = uuid4()
        ops = [{"op": "add_node", "node_type": "filter", "label": "F", "config": {}}]
        state = _make_state(build_plan={"workflow_id": wf_id, "ops": ops, "summary": ""})

        mock_session = _mock_build_session(session_id)
        mock_node = MagicMock()
        mock_node.node_id = "node_test"
        mock_node.to_dict = MagicMock(return_value={"id": "node_test", "type": "filter", "data": {}})

        publish_mock, published_events = _mock_publish_recording()
        factory, _ = _mock_async_session_factory()

        with (
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget", return_value=(True, None)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.create", AsyncMock(return_value=mock_session)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_node", AsyncMock(return_value=mock_node)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_edge", AsyncMock(return_value=None)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.cancel", AsyncMock(return_value=mock_session)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.set_audit", AsyncMock()),
            patch("app.services.agent.graph.nodes.build_workflow.async_session_factory", factory),
            patch("app.services.agent.graph.nodes.build_workflow.definition_event_service.publish", publish_mock),
            patch("app.services.agent.graph.nodes.build_workflow.interrupt", return_value={"action": "cancel"}),
            patch("app.services.agent.graph.nodes.build_workflow._write_audit", AsyncMock()),
        ):
            result = await build_workflow_node(state)

        assert "build_cancelled" in published_events
        assert "cancelada" in result["final_report"].lower()

    @pytest.mark.asyncio
    async def test_sql_script_node_gets_analysis_injected(self):
        """sql_script nodes devem ter _sql_analysis injetado no data."""
        wf_id = str(uuid4())
        session_id = uuid4()
        ops = [
            {"op": "add_node", "node_type": "sql_script", "label": "Query",
             "config": {"query": "SELECT * FROM orders WHERE id = :I_ID"}},
        ]
        state = _make_state(build_plan={"workflow_id": wf_id, "ops": ops, "summary": ""})

        captured_data: list[dict] = []
        mock_session = _mock_build_session(session_id)

        async def _capture_add_node(sid, *, node_type, position, data):
            captured_data.append(dict(data))
            n = MagicMock()
            n.node_id = "node_sql"
            n.to_dict = MagicMock(return_value={"id": "node_sql", "type": "sql_script", "data": data})
            return n

        publish_mock, _ = _mock_publish_recording()
        factory, _ = _mock_async_session_factory()

        with (
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget", return_value=(True, None)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.create", AsyncMock(return_value=mock_session)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_node", side_effect=_capture_add_node),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_edge", AsyncMock(return_value=None)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.set_audit", AsyncMock()),
            patch("app.services.agent.graph.nodes.build_workflow.async_session_factory", factory),
            patch("app.services.agent.graph.nodes.build_workflow.definition_event_service.publish", publish_mock),
            patch("app.services.agent.graph.nodes.build_workflow.interrupt", return_value={"action": "cancel"}),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.cancel", AsyncMock()),
            patch("app.services.agent.graph.nodes.build_workflow._write_audit", AsyncMock()),
        ):
            await build_workflow_node(state)

        assert len(captured_data) == 1
        assert "_sql_analysis" in captured_data[0]
        analysis = captured_data[0]["_sql_analysis"]
        assert analysis["destructiveness"] == "safe"
        assert any(b["name"] == "I_ID" for b in analysis["binds"])
