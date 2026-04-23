"""
FASE 7 — testes das quatro correcoes do backend.

G1: Guardrail destrutivo escalado via interrupt() em build_workflow_node
G2: SharedListener — um asyncpg.connect por canal, N subscribers
G3: Budget enforcement — check_build_budget em create_build_session; ops limit em pending_add_node
G4: cleanup_expired remove sessoes expiradas, preserva ativas
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.build_session_service import (
    BuildSessionService,
    _BUILD_SESSIONS_PER_USER_PER_DAY,
    _MAX_OPS_PER_SESSION,
    _SESSION_TTL_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(workspace_role: str = "MANAGER") -> MagicMock:
    ctx = MagicMock()
    ctx.workspace_role = workspace_role
    ctx.user_id = uuid4()
    ctx.workspace_id = uuid4()
    ctx.project_id = None
    ctx.project_role = "EDITOR"
    ctx.organization_id = uuid4()
    ctx.organization_role = "MEMBER"
    return ctx


# ---------------------------------------------------------------------------
# G1 — Guardrail destrutivo: roteia por request_human_approval (agent_approvals)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g1_destructive_sql_routes_through_human_approval() -> None:
    """SQL destrutivo deve rotear por request_human_approval (agent_approvals +
    thread_status), reutilizando o mesmo caminho de auditoria do
    human_approval_node — NAO um interrupt paralelo com tipo custom."""
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    from app.services.agent.graph.state import PlatformAgentState

    wf_id = str(uuid4())
    thread_id = str(uuid4())
    captured_calls: list[dict] = []

    async def fake_request_human_approval(**kwargs):
        captured_calls.append(kwargs)
        # Simula usuario recusando para encerrar o node cedo sem mockar o resto.
        return (False, "approval-id-fake", "Recusado em teste")

    fake_analysis = {
        "destructiveness": "schema_change",
        "tables": [{"table": "clientes", "schema": None, "operation": "DDL"}],
        "binds": [],
        "statement_count": 1,
        "suggested_input_schema": None,
    }

    state: PlatformAgentState = {
        "thread_id": thread_id,
        "messages": [],
        "current_intent": {"intent": "build_workflow"},
        "build_plan": {
            "workflow_id": wf_id,
            "summary": "teste destrutivo",
            "ops": [
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t1",
                        "node_type": "sql_script",
                        "label": "Drop tabela",
                        "config": {"query": "DROP TABLE clientes;"},
                    },
                }
            ],
        },
        "user_context": {"user_id": str(uuid4())},
        "workflow_context": None,
        "final_report": None,
        "guardrails_violation": None,
    }

    with patch(
        "app.services.agent.graph.nodes.build_workflow.request_human_approval",
        side_effect=fake_request_human_approval,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.analyze_sql_script",
        return_value=fake_analysis,
    ):
        result = await build_workflow_node(state)

    # Helper padrao de aprovacao deve ter sido invocado
    assert len(captured_calls) == 1, "request_human_approval deve ser chamado uma vez"
    kwargs = captured_calls[0]
    assert kwargs["thread_id"] == thread_id
    # Tipo padrao "approval_required" (sem tipo custom paralelo)
    assert kwargs.get("approval_type", "approval_required") == "approval_required"
    plan = kwargs["plan_payload"]
    assert plan.get("intent") == "build_workflow"
    # Plano deve comunicar tabelas destrutivas em algum campo visivel
    plan_text = (plan.get("summary") or "") + (plan.get("impact") or "")
    assert "clientes" in plan_text
    # Deve haver ao menos um step com requires_approval=True
    assert any(
        tc.get("requires_approval") is True
        for step in plan.get("steps", [])
        for tc in step.get("tool_calls", [])
    ), "plan_payload deve marcar requires_approval=True em tool_calls destrutivas"

    # Como usuario recusou no helper, node deve abortar com guardrails_violation
    assert result.get("guardrails_violation"), "Rejeicao deve bloquear a construcao"
    final_report = (result.get("final_report") or "").lower()
    assert "destrutivo" in final_report
    assert "abortada" in final_report


@pytest.mark.asyncio
async def test_g1_destructive_sql_proceeds_when_approved() -> None:
    """Quando usuario aprova SQL destrutivo, node deve continuar o fluxo de build."""
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    from app.services.agent.graph.state import PlatformAgentState

    wf_id = str(uuid4())
    thread_id = str(uuid4())

    async def fake_request_human_approval(**kwargs):
        # Simula aprovacao
        return (True, "approval-id-ok", None)

    fake_analysis = {
        "destructiveness": "destructive",
        "tables": [{"table": "pedidos", "schema": None, "operation": "DELETE"}],
        "binds": [],
        "statement_count": 1,
        "suggested_input_schema": None,
    }

    state: PlatformAgentState = {
        "thread_id": thread_id,
        "messages": [],
        "current_intent": {"intent": "build_workflow"},
        "build_plan": {
            "workflow_id": wf_id,
            "summary": "limpeza aprovada",
            "ops": [
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t1",
                        "node_type": "sql_script",
                        "label": "Limpa pedidos",
                        "config": {"query": "DELETE FROM pedidos WHERE id = :id;"},
                    },
                }
            ],
        },
        "user_context": {"user_id": str(uuid4())},
        "workflow_context": None,
        "final_report": None,
        "guardrails_violation": None,
    }

    # Encerra antes do interrupt de build_ready para manter o teste focado.
    def stop_at_build_ready(payload):
        raise RuntimeError("stopped_at_build_ready")

    with patch(
        "app.services.agent.graph.nodes.build_workflow.request_human_approval",
        side_effect=fake_request_human_approval,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.analyze_sql_script",
        return_value=fake_analysis,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.build_session_service"
    ) as mock_bss, patch(
        "app.services.agent.graph.nodes.build_workflow.definition_event_service"
    ) as mock_des, patch(
        "app.services.agent.graph.nodes.build_workflow.async_session_factory"
    ), patch(
        "app.services.agent.graph.nodes.build_workflow._run_new_format_ops",
        new_callable=AsyncMock,
        return_value=(1, 0),
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.interrupt",
        side_effect=stop_at_build_ready,
    ):
        mock_bss.check_build_budget = MagicMock(return_value=(True, None))
        mock_bss.create = AsyncMock(
            return_value=MagicMock(session_id=uuid4(), workflow_id=UUID(wf_id))
        )
        mock_bss.set_audit = AsyncMock()
        mock_des.publish = AsyncMock()
        try:
            await build_workflow_node(state)
        except RuntimeError as exc:
            assert "stopped_at_build_ready" in str(exc)

    # Se chegou ate o build_ready interrupt, a aprovacao destrutiva foi aceita
    # e o build_session foi criado.
    mock_bss.create.assert_called_once()


@pytest.mark.asyncio
async def test_g1_destructive_sql_without_thread_aborts() -> None:
    """Sem thread_id nao e possivel registrar agent_approvals — node aborta."""
    from uuid import UUID as _UUID  # noqa: F401
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    from app.services.agent.graph.state import PlatformAgentState

    wf_id = str(uuid4())

    fake_analysis = {
        "destructiveness": "schema_change",
        "tables": [{"table": "estoque", "schema": None, "operation": "DDL"}],
        "binds": [],
        "statement_count": 1,
        "suggested_input_schema": None,
    }

    state: PlatformAgentState = {
        # thread_id ausente deliberadamente
        "messages": [],
        "current_intent": {"intent": "build_workflow"},
        "build_plan": {
            "workflow_id": wf_id,
            "summary": "teste sem thread",
            "ops": [
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t1",
                        "node_type": "sql_script",
                        "label": "drop",
                        "config": {"query": "DROP TABLE estoque;"},
                    },
                }
            ],
        },
        "user_context": {"user_id": str(uuid4())},
        "workflow_context": None,
        "final_report": None,
        "guardrails_violation": None,
    }

    helper_called: list = []

    async def fake_request_human_approval(**kwargs):
        helper_called.append(kwargs)
        return (True, "x", None)

    with patch(
        "app.services.agent.graph.nodes.build_workflow.request_human_approval",
        side_effect=fake_request_human_approval,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.analyze_sql_script",
        return_value=fake_analysis,
    ):
        result = await build_workflow_node(state)

    assert not helper_called, "Sem thread_id o helper NAO deve ser chamado"
    assert result.get("guardrails_violation")
    assert "thread" in (result.get("final_report") or "").lower()


@pytest.mark.asyncio
async def test_g1_select_only_no_interrupt() -> None:
    """SQL apenas SELECT nao deve chamar interrupt."""
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    from app.services.agent.graph.state import PlatformAgentState

    wf_id = uuid4()
    state: PlatformAgentState = {
        "messages": [],
        "current_intent": {"intent": "build_workflow"},
        "build_plan": {
            "workflow_id": str(wf_id),
            "summary": "teste select",
            "ops": [
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t1",
                        "node_type": "sql_script",
                        "label": "Select clientes",
                        "config": {"query": "SELECT * FROM clientes WHERE id = :id;"},
                    },
                }
            ]
        },
        "workflow_context": None,
        "final_report": None,
        "guardrails_violation": None,
    }

    interrupt_calls: list[dict] = []

    def fake_interrupt(payload):
        interrupt_calls.append(payload)
        # For build_ready, return None (normal LangGraph pause)
        # For destructive_approval_required, we should never get here

    fake_analysis_safe = {
        "destructiveness": "safe",
        "tables": [{"name": "clientes", "schema": None, "alias": None}],
        "binds": [":id"],
        "statement_count": 1,
        "suggested_input_schema": None,
    }

    with patch(
        "app.services.agent.graph.nodes.build_workflow.interrupt", side_effect=fake_interrupt
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.analyze_sql_script",
        return_value=fake_analysis_safe,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.build_session_service"
    ) as mock_bss, patch(
        "app.services.agent.graph.nodes.build_workflow.definition_event_service"
    ) as mock_des, patch(
        "app.services.agent.graph.nodes.build_workflow.async_session_factory"
    ), patch(
        "app.services.agent.graph.nodes.build_workflow._run_new_format_ops",
        new_callable=AsyncMock,
        return_value=([], []),
    ):
        mock_bss.check_build_budget = MagicMock(return_value=(True, None))
        mock_bss.create = AsyncMock(return_value=MagicMock(session_id=uuid4(), workflow_id=wf_id))
        mock_bss.set_audit = AsyncMock()
        mock_des.publish = AsyncMock()
        try:
            await build_workflow_node(state)
        except Exception:
            pass

    # Only interrupt call should be build_ready, never destructive_approval_required
    destructive_calls = [c for c in interrupt_calls if c.get("type") == "destructive_approval_required"]
    assert len(destructive_calls) == 0


# ---------------------------------------------------------------------------
# G2 — SharedListener: uma conexao asyncpg para N subscribers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g2_shared_listener_single_connection() -> None:
    """10 subscribers no mesmo canal devem usar apenas 1 asyncpg.connect."""
    import app.services.definition_event_service as des_module

    # Clear any existing listeners
    des_module._listeners.clear()

    connect_count = 0

    async def fake_connect(dsn):
        nonlocal connect_count
        connect_count += 1
        conn = AsyncMock()
        conn.is_closed.return_value = False
        conn.add_listener = AsyncMock()
        conn.close = AsyncMock()
        return conn

    channel = f"wfdef_{uuid4().hex}"

    with patch("asyncpg.connect", side_effect=fake_connect):
        listener = des_module.SharedListener(channel)
        # Wait for _connect() to finish
        if listener._connect_task:
            await listener._connect_task

        sub_ids = []
        for _ in range(10):
            sub_id, _ = await listener.subscribe()
            sub_ids.append(sub_id)

    assert connect_count == 1, f"Expected 1 connect, got {connect_count}"

    # Cleanup
    for sub_id in sub_ids:
        await listener.unsubscribe(sub_id)
    des_module._listeners.clear()


@pytest.mark.asyncio
async def test_g2_shared_listener_broadcasts_to_all() -> None:
    """Notificacao deve ser entregue a todos os subscribers."""
    import app.services.definition_event_service as des_module

    des_module._listeners.clear()

    async def fake_connect(dsn):
        conn = AsyncMock()
        conn.is_closed.return_value = False
        conn.add_listener = AsyncMock()
        conn.close = AsyncMock()
        return conn

    channel = f"wfdef_{uuid4().hex}"

    with patch("asyncpg.connect", side_effect=fake_connect):
        listener = des_module.SharedListener(channel)
        if listener._connect_task:
            await listener._connect_task

        _, q1 = await listener.subscribe()
        _, q2 = await listener.subscribe()

    # Simula broadcast
    listener._broadcast('{"seq": 1, "event_type": "node_added"}')

    assert not q1.empty()
    assert not q2.empty()
    assert q1.get_nowait() == '{"seq": 1, "event_type": "node_added"}'
    assert q2.get_nowait() == '{"seq": 1, "event_type": "node_added"}'

    des_module._listeners.clear()


# ---------------------------------------------------------------------------
# G3 — Budget: check_build_budget + ops limit
# ---------------------------------------------------------------------------


def test_g3_budget_exceeded_returns_false():
    """Depois de _BUILD_SESSIONS_PER_USER_PER_DAY sessoes, check retorna False."""
    svc = BuildSessionService()
    user_id = str(uuid4())
    # Inject fake log entries directly
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    svc._user_session_log[user_id] = [now] * _BUILD_SESSIONS_PER_USER_PER_DAY

    ok, reason = svc.check_build_budget(user_id)
    assert not ok
    assert reason is not None
    assert str(_BUILD_SESSIONS_PER_USER_PER_DAY) in reason


def test_g3_budget_ok_for_fresh_user():
    svc = BuildSessionService()
    ok, reason = svc.check_build_budget(str(uuid4()))
    assert ok
    assert reason is None


@pytest.mark.asyncio
async def test_g3_ops_limit_exceeded():
    """Ao atingir _MAX_OPS_PER_SESSION nos, pending_add_node retorna OPS_LIMIT_EXCEEDED."""
    import json
    from app.services.agent.tools.workflow_pending_tools import pending_add_node

    session_id = uuid4()
    ctx = _make_ctx()

    with patch(
        "app.services.agent.tools.workflow_pending_tools.build_session_service"
    ) as mock_bss:
        mock_bss.has_temp_id = AsyncMock(return_value=False)
        mock_bss.pending_node_count = AsyncMock(return_value=_MAX_OPS_PER_SESSION)

        result = await pending_add_node(
            db=AsyncMock(),
            ctx=ctx,
            session_id=str(session_id),
            temp_id="t_new",
            node_type="filter",
            label="Filtro extra",
        )

    data = json.loads(result)
    assert data["error"]["code"] == "OPS_LIMIT_EXCEEDED"
    assert data["error"]["details"]["limit"] == _MAX_OPS_PER_SESSION
    assert data["error"]["details"]["current"] == _MAX_OPS_PER_SESSION


@pytest.mark.asyncio
async def test_g3_ops_below_limit_proceeds():
    """Abaixo do limite, pending_add_node deve continuar normalmente."""
    import json
    from app.services.agent.tools.workflow_pending_tools import pending_add_node

    session_id = uuid4()
    ctx = _make_ctx()
    wf_id = uuid4()

    mock_node = MagicMock()
    mock_node.node_id = "node_abc"
    mock_node.to_dict.return_value = {"id": "node_abc", "type": "filter"}

    mock_session = MagicMock()
    mock_session.workflow_id = wf_id

    with patch(
        "app.services.agent.tools.workflow_pending_tools.build_session_service"
    ) as mock_bss, patch(
        "app.services.agent.tools.workflow_pending_tools.definition_event_service"
    ) as mock_des, patch(
        "app.services.agent.tools.workflow_pending_tools.async_session_factory"
    ):
        mock_bss.has_temp_id = AsyncMock(return_value=False)
        mock_bss.pending_node_count = AsyncMock(return_value=_MAX_OPS_PER_SESSION - 1)
        mock_bss.add_pending_node = AsyncMock(return_value=mock_node)
        mock_bss.get = AsyncMock(return_value=mock_session)
        mock_des.publish = AsyncMock()

        result = await pending_add_node(
            db=AsyncMock(),
            ctx=ctx,
            session_id=str(session_id),
            temp_id="t_ok",
            node_type="filter",
            label="OK",
        )

    data = json.loads(result)
    assert "error" not in data
    assert data["node_id"] == "node_abc"


# ---------------------------------------------------------------------------
# G4 — cleanup_expired: remove expiradas, preserva ativas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g4_cleanup_removes_expired_keeps_active():
    svc = BuildSessionService()
    wf_id = uuid4()

    s_active = await svc.create(wf_id)
    s_expired = await svc.create(wf_id)
    # Expire s_expired manually
    s_expired.created_at = datetime.now(timezone.utc) - timedelta(
        seconds=_SESSION_TTL_SECONDS + 1
    )

    removed = await svc.cleanup_expired()
    assert removed == 1
    assert await svc.count() == 1

    still_there = await svc.get(s_active.session_id)
    assert still_there is not None

    gone = await svc.get(s_expired.session_id)
    assert gone is None


@pytest.mark.asyncio
async def test_g4_cleanup_no_expired():
    svc = BuildSessionService()
    await svc.create(uuid4())
    removed = await svc.cleanup_expired()
    assert removed == 0
    assert await svc.count() == 1
