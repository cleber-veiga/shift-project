"""
Testes para BuildSessionService.

Abordagem: sem banco nem Redis — tudo em memoria.
Testa: criacao, add/update/remove de nos e arestas, confirm (idempotente),
cancel, expiracao de TTL e limpeza.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.build_session_service import (
    BuildSession,
    BuildSessionService,
    BuildSessionNotFoundError,
    ConfirmResult,
    _SESSION_TTL_SECONDS,
)


def _make_db(wf=None):
    """Mock AsyncSession with a workflow result."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


def _make_workflow(wf_id):
    wf = MagicMock()
    wf.id = wf_id
    wf.definition = {"nodes": [], "edges": [], "variables": []}
    return wf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc() -> BuildSessionService:
    return BuildSessionService()


@pytest.fixture()
def wf_id():
    return uuid4()


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_session(svc, wf_id):
    session = await svc.create(wf_id)
    assert str(session.workflow_id) == str(wf_id)
    assert not session.confirmed
    assert not session.cancelled
    assert session.is_active()


@pytest.mark.asyncio
async def test_create_generates_unique_ids(svc, wf_id):
    s1 = await svc.create(wf_id)
    s2 = await svc.create(wf_id)
    assert s1.session_id != s2.session_id


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_existing_session(svc, wf_id):
    session = await svc.create(wf_id)
    found = await svc.get(session.session_id)
    assert found is not None
    assert found.session_id == session.session_id


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(svc):
    result = await svc.get(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_expired_returns_none_and_purges(svc, wf_id):
    session = await svc.create(wf_id)
    # Simula expiracao movendo created_at para o passado
    session.created_at = datetime.now(timezone.utc) - timedelta(seconds=_SESSION_TTL_SECONDS + 1)

    result = await svc.get(session.session_id)
    assert result is None
    # Deve ter sido removida
    assert await svc.count() == 0


# ---------------------------------------------------------------------------
# pending nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_pending_node_happy_path(svc, wf_id):
    session = await svc.create(wf_id)
    node = await svc.add_pending_node(
        session.session_id,
        node_type="filter",
        position={"x": 100, "y": 200},
        data={"conditions": []},
    )
    assert node is not None
    assert node.node_id.startswith("node_")
    assert node.node_type == "filter"
    d = node.to_dict()
    assert d["data"]["__pending"] is True


@pytest.mark.asyncio
async def test_add_pending_node_invalid_session_returns_none(svc):
    result = await svc.add_pending_node(
        uuid4(),
        node_type="filter",
        position={"x": 0, "y": 0},
        data={},
    )
    assert result is None


@pytest.mark.asyncio
async def test_update_pending_node_merges_data(svc, wf_id):
    session = await svc.create(wf_id)
    node = await svc.add_pending_node(
        session.session_id,
        node_type="filter",
        position={"x": 0, "y": 0},
        data={"a": 1},
    )
    assert node is not None
    updated = await svc.update_pending_node(session.session_id, node.node_id, {"b": 2})
    assert updated is not None
    assert updated.data == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_update_pending_node_overwrite_key(svc, wf_id):
    session = await svc.create(wf_id)
    node = await svc.add_pending_node(
        session.session_id,
        node_type="filter",
        position={"x": 0, "y": 0},
        data={"label": "antigo"},
    )
    assert node is not None
    updated = await svc.update_pending_node(session.session_id, node.node_id, {"label": "novo"})
    assert updated is not None
    assert updated.data["label"] == "novo"


@pytest.mark.asyncio
async def test_update_pending_node_not_found_returns_none(svc, wf_id):
    session = await svc.create(wf_id)
    result = await svc.update_pending_node(session.session_id, "node_inexistente", {"x": 1})
    assert result is None


@pytest.mark.asyncio
async def test_remove_pending_node_and_cascades_edges(svc, wf_id):
    session = await svc.create(wf_id)
    n1 = await svc.add_pending_node(session.session_id, node_type="filter", position={"x": 0, "y": 0}, data={})
    n2 = await svc.add_pending_node(session.session_id, node_type="mapper", position={"x": 200, "y": 0}, data={})
    assert n1 and n2

    # Aresta entre n1 e n2 (deve ser removida junto com n1)
    edge = await svc.add_pending_edge(session.session_id, source=n1.node_id, target=n2.node_id)
    assert edge is not None

    removed = await svc.remove_pending_node(session.session_id, n1.node_id)
    assert removed is not None
    assert removed.node_id == n1.node_id

    fresh = await svc.get(session.session_id)
    assert fresh is not None
    assert n1.node_id not in fresh.pending_nodes
    assert edge.edge_id not in fresh.pending_edges  # cascata


@pytest.mark.asyncio
async def test_remove_pending_node_not_found_returns_none(svc, wf_id):
    session = await svc.create(wf_id)
    result = await svc.remove_pending_node(session.session_id, "node_xxx")
    assert result is None


# ---------------------------------------------------------------------------
# pending edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_pending_edge_happy_path(svc, wf_id):
    session = await svc.create(wf_id)
    edge = await svc.add_pending_edge(
        session.session_id,
        source="node_a",
        target="node_b",
        source_handle="success",
    )
    assert edge is not None
    assert edge.edge_id.startswith("edge_")
    d = edge.to_dict()
    assert d["__pending"] is True
    assert d["sourceHandle"] == "success"
    assert "targetHandle" not in d


@pytest.mark.asyncio
async def test_add_pending_edge_invalid_session(svc):
    result = await svc.add_pending_edge(uuid4(), source="a", target="b")
    assert result is None


@pytest.mark.asyncio
async def test_remove_pending_edge_happy_path(svc, wf_id):
    session = await svc.create(wf_id)
    edge = await svc.add_pending_edge(session.session_id, source="a", target="b")
    assert edge is not None

    removed = await svc.remove_pending_edge(session.session_id, edge.edge_id)
    assert removed is not None
    assert removed.edge_id == edge.edge_id

    fresh = await svc.get(session.session_id)
    assert fresh is not None
    assert edge.edge_id not in fresh.pending_edges


@pytest.mark.asyncio
async def test_remove_pending_edge_not_found(svc, wf_id):
    session = await svc.create(wf_id)
    result = await svc.remove_pending_edge(session.session_id, "edge_xxx")
    assert result is None


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_happy_path(svc, wf_id):
    import app.services.definition_event_service as des_module
    session = await svc.create(wf_id)
    await svc.add_pending_node(session.session_id, node_type="filter", position={"x": 0, "y": 0}, data={})
    db = _make_db(_make_workflow(wf_id))
    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock), \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock):
        result = await svc.confirm(session.session_id, db)
    assert isinstance(result, ConfirmResult)
    assert result.nodes_added == 1


@pytest.mark.asyncio
async def test_confirm_idempotent(svc, wf_id):
    import app.services.definition_event_service as des_module
    session = await svc.create(wf_id)
    db1 = _make_db(_make_workflow(wf_id))
    db2 = _make_db(_make_workflow(wf_id))
    with patch.object(des_module.definition_event_service, "publish_within_tx", new_callable=AsyncMock), \
         patch.object(des_module.definition_event_service, "publish", new_callable=AsyncMock):
        r1 = await svc.confirm(session.session_id, db1)
        # Second confirm on already-confirmed session still returns ConfirmResult (idempotent)
        r2 = await svc.confirm(session.session_id, db2)
    assert isinstance(r1, ConfirmResult)
    assert isinstance(r2, ConfirmResult)


@pytest.mark.asyncio
async def test_confirm_nonexistent_raises(svc):
    db = _make_db()
    with pytest.raises(BuildSessionNotFoundError):
        await svc.confirm(uuid4(), db)


@pytest.mark.asyncio
async def test_confirm_cancelled_raises(svc, wf_id):
    session = await svc.create(wf_id)
    await svc.cancel(session.session_id)
    db = _make_db()
    with pytest.raises(BuildSessionNotFoundError):
        await svc.confirm(session.session_id, db)


@pytest.mark.asyncio
async def test_confirm_expired_raises(svc, wf_id):
    session = await svc.create(wf_id)
    session.created_at = datetime.now(timezone.utc) - timedelta(seconds=_SESSION_TTL_SECONDS + 1)
    db = _make_db()
    with pytest.raises(BuildSessionNotFoundError):
        await svc.confirm(session.session_id, db)


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_happy_path(svc, wf_id):
    session = await svc.create(wf_id)
    result = await svc.cancel(session.session_id)
    assert result is not None
    assert result.cancelled is True
    # Deve ser removida da memoria
    assert await svc.count() == 0


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_none(svc):
    result = await svc.cancel(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_add_node_after_cancel_returns_none(svc, wf_id):
    session = await svc.create(wf_id)
    await svc.cancel(session.session_id)
    result = await svc.add_pending_node(
        session.session_id,
        node_type="filter",
        position={"x": 0, "y": 0},
        data={},
    )
    assert result is None


# ---------------------------------------------------------------------------
# cleanup_expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_removes_expired(svc, wf_id):
    s1 = await svc.create(wf_id)
    s2 = await svc.create(wf_id)
    # Expira s1
    s1.created_at = datetime.now(timezone.utc) - timedelta(seconds=_SESSION_TTL_SECONDS + 1)

    removed = await svc.cleanup_expired()
    assert removed == 1
    assert await svc.count() == 1


@pytest.mark.asyncio
async def test_cleanup_no_expired(svc, wf_id):
    await svc.create(wf_id)
    removed = await svc.cleanup_expired()
    assert removed == 0


# ---------------------------------------------------------------------------
# Concorrencia: garantia de thread-safety do lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_add_nodes_unique_ids(svc, wf_id):
    session = await svc.create(wf_id)
    results = await asyncio.gather(*[
        svc.add_pending_node(
            session.session_id,
            node_type="filter",
            position={"x": i * 10.0, "y": 0},
            data={},
        )
        for i in range(20)
    ])
    node_ids = [r.node_id for r in results if r is not None]
    assert len(node_ids) == 20
    assert len(set(node_ids)) == 20  # todos unicos
