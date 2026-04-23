"""
Testes de atomicidade e idempotencia para os endpoints de build session.

Abordagem: invoca as funcoes async diretamente (sem TestClient HTTP),
mockando db, build_session_service e definition_event_service.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.api.v1.workflow_build as build_module
import app.services.build_session_service as bss_module
import app.services.definition_event_service as des_module
from app.api.v1.workflow_build import (
    ConfirmBuildResponse,
    confirm_build_session,
    undo_build_session,
)
from app.models.workflow_definition_event import WorkflowDefinitionEvent
from app.services.build_session_service import (
    BuildSession,
    BuildSessionNotFoundError,
    ConfirmResult,
    PendingEdge,
    PendingNode,
    _confirm_idem_cache,
    build_session_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(nodes=None, edges=None):
    wf = MagicMock()
    wf.id = uuid.uuid4()
    wf.definition = {"nodes": nodes or [], "edges": edges or [], "variables": []}
    return wf


def _make_session(workflow_id, nodes=None, edges=None, confirmed=False):
    session = MagicMock(spec=BuildSession)
    session.workflow_id = workflow_id
    session.confirmed = confirmed
    session.pending_nodes = nodes or {}
    session.pending_edges = edges or {}
    return session


def _make_db(wf=None):
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# confirm_build_session — transacao atomica
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_uses_publish_within_tx_and_single_commit():
    """build_session_service.confirm() deve usar publish_within_tx para cada evento
    e chamar db.commit() exatamente uma vez ao final."""
    wf_id = uuid.uuid4()
    session_id = uuid.uuid4()

    node = PendingNode(node_id="node_abc", node_type="sql_script", position={"x": 0, "y": 0}, data={})
    wf = _make_workflow()
    db = _make_db(wf)

    # Injeta sessao pre-populada no servico
    from app.services.build_session_service import BuildSessionService, BuildSession
    from datetime import datetime, timezone
    svc = BuildSessionService()
    sess = BuildSession(
        session_id=session_id,
        workflow_id=wf_id,
        created_at=datetime.now(timezone.utc),
        pending_nodes={"node_abc": node},
    )
    async with svc._lock:
        svc._sessions[str(session_id)] = sess

    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock) as mock_wtx, \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock) as mock_pub:

        result = await svc.confirm(session_id, db, idempotency_key=None)

    assert isinstance(result, ConfirmResult)
    assert result.nodes_added == 1
    # publish_within_tx para node_added + build_confirmed = 2 chamadas
    assert mock_wtx.await_count == 2
    # publish (com commit proprio) nao deve ser chamado no caminho feliz
    mock_pub.assert_not_awaited()
    # commit exatamente uma vez
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_rollback_on_flush_failure():
    """Se db.flush() falhar, confirm deve fazer rollback e publicar build_failed
    em transacao nova. db.commit() nao deve ter sido chamado."""
    wf_id = uuid.uuid4()
    session_id = uuid.uuid4()

    wf = _make_workflow()
    db = _make_db(wf)
    db.flush = AsyncMock(side_effect=RuntimeError("flush explodiu"))

    from app.services.build_session_service import BuildSessionService, BuildSession
    from datetime import datetime, timezone
    svc = BuildSessionService()
    sess = BuildSession(
        session_id=session_id,
        workflow_id=wf_id,
        created_at=datetime.now(timezone.utc),
    )
    async with svc._lock:
        svc._sessions[str(session_id)] = sess

    fail_db = _make_db()

    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock), \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock) as mock_pub, \
         patch("app.db.session.async_session_factory") as mock_factory:

        mock_factory.return_value.__aenter__ = AsyncMock(return_value=fail_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(RuntimeError, match="flush explodiu"):
            await svc.confirm(session_id, db, idempotency_key=None)

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    # build_failed publicado na sessao de fallback
    mock_pub.assert_awaited_once()
    call_kwargs = mock_pub.call_args[1]
    assert call_kwargs["event_type"] == "build_failed"


@pytest.mark.asyncio
async def test_confirm_idempotency_key_returns_cached():
    """Duas chamadas com a mesma Idempotency-Key retornam o mesmo resultado
    sem re-aplicar as operacoes na segunda chamada."""
    wf_id = uuid.uuid4()
    session_id = uuid.uuid4()
    idem_key = f"idem-test-{uuid.uuid4().hex}"
    cache_key = f"confirm_idem:{session_id}:{idem_key}"

    _confirm_idem_cache.pop(cache_key, None)

    node = PendingNode(node_id="node_xyz", node_type="sql_script", position={"x": 0, "y": 0}, data={})
    wf = _make_workflow()
    db1 = _make_db(wf)
    db2 = _make_db(wf)

    from app.services.build_session_service import BuildSessionService, BuildSession
    from datetime import datetime, timezone
    svc = BuildSessionService()
    sess = BuildSession(
        session_id=session_id,
        workflow_id=wf_id,
        created_at=datetime.now(timezone.utc),
        pending_nodes={"node_xyz": node},
    )
    async with svc._lock:
        svc._sessions[str(session_id)] = sess

    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock) as mock_wtx, \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock):

        # Primeira chamada — processa normalmente
        r1 = await svc.confirm(session_id, db1, idempotency_key=idem_key)

        # Segunda chamada com mesma chave — deve retornar cache sem re-processar
        r2 = await svc.confirm(session_id, db2, idempotency_key=idem_key)

    assert r1.nodes_added == r2.nodes_added == 1
    # publish_within_tx chamado apenas na primeira requisicao
    assert mock_wtx.await_count == 2  # node_added + build_confirmed, apenas 1x
    # db da segunda chamada nao foi usado
    db2.commit.assert_not_awaited()

    _confirm_idem_cache.pop(cache_key, None)


@pytest.mark.asyncio
async def test_confirm_idempotency_key_expired_reprocesses():
    """Cache expirado deve ser descartado e a requisicao re-processada."""
    wf_id = uuid.uuid4()
    session_id = uuid.uuid4()
    idem_key = f"idem-expired-{uuid.uuid4().hex}"
    cache_key = f"confirm_idem:{session_id}:{idem_key}"

    # Injeta entrada expirada com ConfirmResult
    _confirm_idem_cache[cache_key] = (
        ConfirmResult(nodes_added=99, edges_added=99, session_id=session_id),
        time.monotonic() - 1,  # ja expirou
    )

    wf = _make_workflow()
    db = _make_db(wf)

    from app.services.build_session_service import BuildSessionService, BuildSession
    from datetime import datetime, timezone
    svc = BuildSessionService()
    sess = BuildSession(
        session_id=session_id,
        workflow_id=wf_id,
        created_at=datetime.now(timezone.utc),
    )
    async with svc._lock:
        svc._sessions[str(session_id)] = sess

    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock), \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock):

        result = await svc.confirm(session_id, db, idempotency_key=idem_key)

    # Nao deve ter retornado o valor expirado (99)
    assert result.nodes_added == 0
    db.commit.assert_awaited_once()

    _confirm_idem_cache.pop(cache_key, None)


# ---------------------------------------------------------------------------
# undo_build_session — race fix: instancias do INSERT, nao re-query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undo_uses_insert_instances_not_requery():
    """undo_build_session deve usar as instancias WorkflowDefinitionEvent
    criadas nos INSERTs (apos flush) para o pg_notify, sem re-queryar o banco."""
    wf_id = uuid.uuid4()
    session_id = uuid.uuid4()

    node = PendingNode(node_id="node_del", node_type="sql_script", position={"x": 0, "y": 0}, data={})
    build_session = _make_session(wf_id, nodes={"node_del": node}, confirmed=True)

    existing_nodes = [{"id": "node_del", "type": "sql_script", "position": {"x": 0, "y": 0}, "data": {}}]
    wf = _make_workflow(nodes=existing_nodes)

    db = AsyncMock()
    # SELECT retorna o workflow na primeira chamada
    wf_result = MagicMock()
    wf_result.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=wf_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    added_instances: list[WorkflowDefinitionEvent] = []

    original_add = MagicMock()
    def capture_add(obj):
        if isinstance(obj, WorkflowDefinitionEvent):
            # Simula que flush popula seq/id
            obj.seq = len(added_instances) + 1
            obj.id = uuid.uuid4()
            obj.created_at = None
            added_instances.append(obj)
        original_add(obj)
    db.add = capture_add

    pg_notify_calls: list[str] = []
    original_execute = db.execute

    async def capture_execute(stmt, params=None):
        if params and "ch" in params:
            pg_notify_calls.append(params["ch"])
        return await original_execute(stmt, params)

    db.execute = capture_execute

    with patch.object(build_module.build_session_service, "get", new_callable=AsyncMock, return_value=build_session):
        await undo_build_session(
            workflow_id=wf_id,
            session_id=session_id,
            db=db,
            _=None,
        )

    # Deve ter inserido exatamente 1 evento (node_removed)
    assert len(added_instances) == 1
    assert added_instances[0].event_type == "node_removed"
    # pg_notify chamado com o canal correto, uma vez
    assert len(pg_notify_calls) == 1
    assert pg_notify_calls[0] == f"wfdef_{wf_id.hex}"
    db.commit.assert_awaited_once()
