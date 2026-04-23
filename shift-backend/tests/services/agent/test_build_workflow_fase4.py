"""
FASE 4 — testes do build_workflow node e confirmação in-process.

Cobre:
  - test_build_workflow_node_confirms_inline: interrupt → 'confirm' → service.confirm chamado
  - test_build_workflow_confirm_failure: exception no confirm → relatório de falha, sem sucesso
  - test_build_workflow_session_expired: BuildSessionNotFoundError → mensagem de expiração
  - test_ttl_30min: sessão expira após 30min, não antes
  - test_dead_code_removed: _HEARTBEAT_INTERVAL e import asyncio ausentes do node
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(workflow_id: str | None = None, ops=None) -> dict:
    return {
        "build_plan": {
            "workflow_id": workflow_id or str(uuid.uuid4()),
            "ops": ops or [],
            "summary": "teste",
        },
        "user_context": {"user_id": str(uuid.uuid4())},
        "thread_id": str(uuid.uuid4()),
        "messages": [],
        "token_usage": [],
    }


def _make_session(workflow_id=None):
    session = MagicMock()
    session.session_id = uuid.uuid4()
    session.workflow_id = workflow_id or uuid.uuid4()
    return session


# ---------------------------------------------------------------------------
# test_build_workflow_node_confirms_inline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_workflow_node_confirms_inline():
    """Quando interrupt retorna 'confirm', o node deve chamar build_session_service.confirm()
    inline (dentro do próprio node), não delegar ao REST endpoint."""
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    import app.services.agent.graph.nodes.build_workflow as bw_module

    session = _make_session()
    confirm_result = MagicMock()
    confirm_result.nodes_added = 1
    confirm_result.edges_added = 0

    with patch.object(
        bw_module.build_session_service, "create", new_callable=AsyncMock, return_value=session
    ), patch.object(
        bw_module.build_session_service, "set_audit", new_callable=AsyncMock
    ), patch.object(
        bw_module.build_session_service, "check_build_budget", return_value=(True, None)
    ), patch.object(
        bw_module.build_session_service, "add_pending_node", new_callable=AsyncMock, return_value=None
    ), patch.object(
        bw_module.build_session_service, "add_pending_edge", new_callable=AsyncMock, return_value=None
    ), patch.object(
        bw_module.build_session_service, "confirm", new_callable=AsyncMock, return_value=confirm_result
    ) as mock_confirm, patch.object(
        bw_module.definition_event_service, "publish", new_callable=AsyncMock
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.interrupt",
        return_value={"action": "confirm"},
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.compute_layout",
        return_value=[],
    ), patch(
        "app.services.agent.graph.nodes.build_workflow._write_audit",
        new_callable=AsyncMock,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.async_session_factory",
    ) as mock_factory:
        # Simulate async context manager for db session
        mock_db = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await build_workflow_node(_make_state())

    # confirm() deve ter sido chamado com a session_id e a db session
    mock_confirm.assert_awaited_once()
    call_args = mock_confirm.call_args
    assert call_args[0][0] == session.session_id  # primeiro arg posicional = session_id
    assert call_args[0][1] is mock_db             # segundo arg = db session

    # Relatório deve mencionar sucesso
    assert "adicionados" in result["final_report"]
    assert "1 no(s)" in result["final_report"]


# ---------------------------------------------------------------------------
# test_build_workflow_confirm_failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_workflow_confirm_failure():
    """Se build_session_service.confirm() lançar Exception, node reporta falha
    e NÃO reporta sucesso no final_report."""
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    import app.services.agent.graph.nodes.build_workflow as bw_module

    session = _make_session()

    with patch.object(
        bw_module.build_session_service, "create", new_callable=AsyncMock, return_value=session
    ), patch.object(
        bw_module.build_session_service, "set_audit", new_callable=AsyncMock
    ), patch.object(
        bw_module.build_session_service, "check_build_budget", return_value=(True, None)
    ), patch.object(
        bw_module.build_session_service, "add_pending_node", new_callable=AsyncMock, return_value=None
    ), patch.object(
        bw_module.build_session_service, "add_pending_edge", new_callable=AsyncMock, return_value=None
    ), patch.object(
        bw_module.build_session_service, "confirm",
        new_callable=AsyncMock,
        side_effect=RuntimeError("flush explodiu"),
    ), patch.object(
        bw_module.definition_event_service, "publish", new_callable=AsyncMock
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.interrupt",
        return_value={"action": "confirm"},
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.compute_layout",
        return_value=[],
    ), patch(
        "app.services.agent.graph.nodes.build_workflow._write_audit",
        new_callable=AsyncMock,
    ) as mock_audit, patch(
        "app.services.agent.graph.nodes.build_workflow.async_session_factory",
    ) as mock_factory:
        mock_db = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await build_workflow_node(_make_state())

    # Relatório NÃO deve mencionar sucesso
    assert "adicionados" not in result["final_report"]
    assert "Falha" in result["final_report"]

    # Auditoria com status confirm_failed
    mock_audit.assert_awaited_once()
    audit_kwargs = mock_audit.call_args[1]
    assert audit_kwargs["status"] == "confirm_failed"


# ---------------------------------------------------------------------------
# test_build_workflow_session_expired
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_workflow_session_expired():
    """BuildSessionNotFoundError → relatório de expiração (não de erro de DB)."""
    from app.services.agent.graph.nodes.build_workflow import build_workflow_node
    from app.services.build_session_service import BuildSessionNotFoundError
    import app.services.agent.graph.nodes.build_workflow as bw_module

    session = _make_session()

    with patch.object(
        bw_module.build_session_service, "create", new_callable=AsyncMock, return_value=session
    ), patch.object(
        bw_module.build_session_service, "set_audit", new_callable=AsyncMock
    ), patch.object(
        bw_module.build_session_service, "check_build_budget", return_value=(True, None)
    ), patch.object(
        bw_module.build_session_service, "add_pending_node", new_callable=AsyncMock, return_value=None
    ), patch.object(
        bw_module.build_session_service, "add_pending_edge", new_callable=AsyncMock, return_value=None
    ), patch.object(
        bw_module.build_session_service, "confirm",
        new_callable=AsyncMock,
        side_effect=BuildSessionNotFoundError("expired"),
    ), patch.object(
        bw_module.definition_event_service, "publish", new_callable=AsyncMock
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.interrupt",
        return_value={"action": "confirm"},
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.compute_layout",
        return_value=[],
    ), patch(
        "app.services.agent.graph.nodes.build_workflow._write_audit",
        new_callable=AsyncMock,
    ), patch(
        "app.services.agent.graph.nodes.build_workflow.async_session_factory",
    ) as mock_factory:
        mock_db = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await build_workflow_node(_make_state())

    assert "expirou" in result["final_report"]
    assert "adicionados" not in result["final_report"]


# ---------------------------------------------------------------------------
# test_ttl_30min — Option B: sessão expira após 30min, não em 90s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ttl_30min_session_active_before_expiry():
    """Sessão criada há 29min 59s ainda está ativa (TTL = 30min)."""
    from app.services.build_session_service import BuildSession

    session = BuildSession(
        session_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=29, seconds=59),
    )
    assert session.is_active() is True
    assert session.is_expired() is False


@pytest.mark.asyncio
async def test_ttl_30min_session_expired_after_30min():
    """Sessão criada há 30min+1s está expirada."""
    from app.services.build_session_service import BuildSession

    session = BuildSession(
        session_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30, seconds=1),
    )
    assert session.is_expired() is True
    assert session.is_active() is False


@pytest.mark.asyncio
async def test_cleanup_uses_ttl_only():
    """cleanup_expired() remove sessões expiradas por TTL, não por heartbeat staleness."""
    from app.services.build_session_service import BuildSessionService

    svc = BuildSessionService()

    # Sessão expirada por TTL
    old_session = BuildSession(
        session_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    # Sessão nova (não expirada) sem heartbeat renovado
    new_session = BuildSession(
        session_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    # Injeta diretamente no dicionário interno
    async with svc._lock:
        svc._sessions[str(old_session.session_id)] = old_session
        svc._sessions[str(new_session.session_id)] = new_session

    removed = await svc.cleanup_expired()

    assert removed == 1
    remaining_ids = set(svc._sessions.keys())
    assert str(new_session.session_id) in remaining_ids
    assert str(old_session.session_id) not in remaining_ids


# ---------------------------------------------------------------------------
# test_dead_code_removed — garante que _HEARTBEAT_INTERVAL e asyncio não estão no node
# ---------------------------------------------------------------------------

def test_heartbeat_interval_constant_removed():
    """_HEARTBEAT_INTERVAL não deve mais existir no módulo build_workflow."""
    import app.services.agent.graph.nodes.build_workflow as bw_module
    assert not hasattr(bw_module, "_HEARTBEAT_INTERVAL"), (
        "_HEARTBEAT_INTERVAL é dead code e deve ter sido removido"
    )


def test_asyncio_not_imported_in_build_workflow():
    """O módulo build_workflow não deve importar asyncio (era dead code)."""
    import importlib
    import sys

    # Garante que o módulo está carregado
    import app.services.agent.graph.nodes.build_workflow as bw_module

    # Verifica que asyncio não está no namespace do módulo
    assert "asyncio" not in vars(bw_module), (
        "asyncio era dead code em build_workflow e deve ter sido removido"
    )


# ---------------------------------------------------------------------------
# Import helper for BuildSession in cleanup test
# ---------------------------------------------------------------------------

from app.services.build_session_service import BuildSession  # noqa: E402
