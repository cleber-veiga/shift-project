"""
Testes para DefinitionEventService: publish e get_events_since.

Abordagem: mocks do AsyncSession — sem banco real nem asyncpg.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.definition_event_service import (
    DefinitionEventService,
    _channel,
    _format_sse,
    _row_to_dict,
)

# ---------------------------------------------------------------------------
# publish_within_tx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_within_tx_no_separate_commit():
    """publish_within_tx insere o evento e emite pg_notify SEM chamar db.commit()."""
    svc = DefinitionEventService()
    db = _make_db()
    wid = uuid4()

    mock_event = MagicMock()
    mock_event.seq = 10
    mock_event.id = uuid4()

    with patch(
        "app.services.definition_event_service.WorkflowDefinitionEvent",
        return_value=mock_event,
    ):
        event = await svc.publish_within_tx(
            db,
            workflow_id=wid,
            event_type="node_added",
            payload={"node_id": "n1"},
            client_mutation_id="mut-tx",
        )

    db.add.assert_called_once_with(mock_event)
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()  # commit pertence ao caller
    assert db.execute.await_count >= 1
    # pg_notify deve ter sido chamado com o canal correto
    call_args = db.execute.await_args_list[-1]
    bound_params = call_args[0][1] if call_args[0] else call_args[1]
    assert bound_params.get("ch") == _channel(wid)
    notify_json = json.loads(bound_params["pl"])
    assert notify_json["event_type"] == "node_added"
    assert notify_json["client_mutation_id"] == "mut-tx"
    assert event is mock_event


@pytest.mark.asyncio
async def test_publish_delegates_to_publish_within_tx_then_commits():
    """publish() deve chamar publish_within_tx e em seguida db.commit()."""
    svc = DefinitionEventService()
    db = _make_db()
    mock_event = MagicMock()
    mock_event.seq = 5
    mock_event.id = uuid4()

    with patch.object(svc, "publish_within_tx", new_callable=AsyncMock, return_value=mock_event) as mock_inner:
        result = await svc.publish(
            db,
            workflow_id=uuid4(),
            event_type="edge_added",
            payload={"edge_id": "e1"},
        )

    mock_inner.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert result is mock_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_row(
    *,
    seq: int = 1,
    event_type: str = "node_added",
    payload: dict | None = None,
    client_mutation_id: str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.seq = seq
    row.workflow_id = uuid4()
    row.event_type = event_type
    row.payload = payload or {"node_id": "node_abc123"}
    row.client_mutation_id = client_mutation_id
    row.created_at = MagicMock()
    row.created_at.isoformat.return_value = "2026-04-22T10:00:00+00:00"
    return row


def _make_db(scalars_rows: list | None = None):
    """AsyncSession mock com execute e commit stubados."""
    db = AsyncMock()
    result_mock = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_rows or []
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _channel helper
# ---------------------------------------------------------------------------


def test_channel_format():
    wid = uuid4()
    ch = _channel(wid)
    assert ch == f"wfdef_{wid.hex}"
    assert "-" not in ch
    assert ch.isidentifier()


# ---------------------------------------------------------------------------
# _format_sse helper
# ---------------------------------------------------------------------------


def test_format_sse_structure():
    data = {"seq": 5, "event_type": "node_added", "payload": {"node_id": "abc"}}
    result = _format_sse(5, "node_added", data)
    assert result.startswith("id: 5\n")
    assert "event: node_added\n" in result
    assert "data:" in result
    assert result.endswith("\n\n")


def test_format_sse_body_is_valid_json():
    data = {"x": 1}
    result = _format_sse(1, "test", data)
    data_line = next(l for l in result.splitlines() if l.startswith("data:"))
    parsed = json.loads(data_line[len("data:"):].strip())
    assert parsed == {"x": 1}


# ---------------------------------------------------------------------------
# _row_to_dict helper
# ---------------------------------------------------------------------------


def test_row_to_dict_fields():
    row = _make_event_row(seq=3, event_type="edge_added")
    d = _row_to_dict(row)
    assert d["seq"] == 3
    assert d["event_type"] == "edge_added"
    assert "event_id" in d
    assert "workflow_id" in d
    assert "payload" in d
    assert "ts" in d


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_adds_event_and_commits():
    svc = DefinitionEventService()
    db = _make_db()
    wid = uuid4()

    # Simulate flush populating seq on the event object.
    async def fake_flush():
        pass

    db.flush = AsyncMock(side_effect=fake_flush)

    # We need the event object to have seq populated after flush.
    # Patch WorkflowDefinitionEvent so the constructor returns a mock with seq.
    mock_event = MagicMock()
    mock_event.seq = 42
    mock_event.id = uuid4()

    with patch(
        "app.services.definition_event_service.WorkflowDefinitionEvent",
        return_value=mock_event,
    ):
        event = await svc.publish(
            db,
            workflow_id=wid,
            event_type="node_added",
            payload={"node_id": "node_xyz"},
            client_mutation_id="mut-001",
        )

    db.add.assert_called_once_with(mock_event)
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()
    # pg_notify must have been called via db.execute
    assert db.execute.await_count >= 1
    # Check that pg_notify was invoked with the correct channel
    call_args = db.execute.await_args_list[-1]
    bound_params = call_args[0][1] if call_args[0] else call_args[1]
    assert bound_params.get("ch") == _channel(wid)
    # Payload JSON must include event_type
    notify_json = json.loads(bound_params["pl"])
    assert notify_json["event_type"] == "node_added"
    assert notify_json["client_mutation_id"] == "mut-001"


@pytest.mark.asyncio
async def test_publish_returns_event_object():
    svc = DefinitionEventService()
    db = _make_db()
    mock_event = MagicMock()
    mock_event.seq = 7
    mock_event.id = uuid4()

    with patch(
        "app.services.definition_event_service.WorkflowDefinitionEvent",
        return_value=mock_event,
    ):
        result = await svc.publish(
            db,
            workflow_id=uuid4(),
            event_type="variables_updated",
            payload={"variables": []},
        )

    assert result is mock_event


@pytest.mark.asyncio
async def test_publish_without_client_mutation_id():
    svc = DefinitionEventService()
    db = _make_db()
    mock_event = MagicMock()
    mock_event.seq = 1
    mock_event.id = uuid4()

    with patch(
        "app.services.definition_event_service.WorkflowDefinitionEvent",
        return_value=mock_event,
    ):
        await svc.publish(
            db,
            workflow_id=uuid4(),
            event_type="edge_removed",
            payload={"edge_id": "edge_abc"},
        )

    call_args = db.execute.await_args_list[-1]
    bound_params = call_args[0][1] if call_args[0] else call_args[1]
    notify_json = json.loads(bound_params["pl"])
    assert notify_json["client_mutation_id"] is None


# ---------------------------------------------------------------------------
# get_events_since
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_since_returns_rows():
    svc = DefinitionEventService()
    rows = [_make_event_row(seq=i) for i in range(1, 6)]
    db = _make_db(scalars_rows=rows)
    wid = uuid4()

    result = await svc.get_events_since(db, workflow_id=wid, since_seq=0)

    assert result == rows
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_events_since_filters_by_seq():
    """Verifica que a query inclui o filtro seq > since_seq (verificado via execute chamado)."""
    svc = DefinitionEventService()
    db = _make_db(scalars_rows=[])
    wid = uuid4()

    await svc.get_events_since(db, workflow_id=wid, since_seq=99)

    # Deve ter chamado execute uma vez (SELECT com filtros)
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_events_since_empty():
    svc = DefinitionEventService()
    db = _make_db(scalars_rows=[])
    result = await svc.get_events_since(db, workflow_id=uuid4(), since_seq=0)
    assert result == []


# ---------------------------------------------------------------------------
# write tools publish integration (smoke test com mock do service)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_node_publishes_event_within_tx():
    """Garante que add_node chama definition_event_service.publish_within_tx."""
    from unittest.mock import patch as _patch
    from app.services.agent.context import UserContext
    from app.services.agent.tools.workflow_write_tools import add_node

    ws_id = uuid4()
    ctx = UserContext(
        user_id=uuid4(),
        workspace_id=ws_id,
        project_id=uuid4(),
        workspace_role="MANAGER",
        project_role="EDITOR",
        organization_id=ws_id,
        organization_role=None,
    )
    wf = MagicMock()
    wf.id = uuid4()
    wf.workspace_id = ws_id
    wf.project_id = None
    wf.definition = {"nodes": [], "edges": [], "variables": []}

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    publish_within_tx_mock = AsyncMock()
    with _patch("app.services.agent.tools.workflow_write_tools.definition_event_service") as mock_svc:
        mock_svc.publish_within_tx = publish_within_tx_mock
        mock_svc.publish = AsyncMock()
        result = await add_node(
            db=db,
            ctx=ctx,
            workflow_id=str(wf.id),
            node_type="filter",
            position={"x": 100, "y": 200},
        )

    assert json.loads(result).get("node_id") is not None
    publish_within_tx_mock.assert_awaited_once()
    call_kwargs = publish_within_tx_mock.call_args[1]
    assert call_kwargs["event_type"] == "node_added"
    assert call_kwargs["payload"]["node_type"] == "filter"


@pytest.mark.asyncio
async def test_remove_edge_publishes_event_within_tx():
    """Garante que remove_edge chama definition_event_service.publish_within_tx."""
    from unittest.mock import patch as _patch
    from app.services.agent.context import UserContext
    from app.services.agent.tools.workflow_write_tools import remove_edge

    ws_id = uuid4()
    ctx = UserContext(
        user_id=uuid4(),
        workspace_id=ws_id,
        project_id=uuid4(),
        workspace_role="MANAGER",
        project_role="EDITOR",
        organization_id=ws_id,
        organization_role=None,
    )
    edge_id = "edge_test123"
    wf = MagicMock()
    wf.id = uuid4()
    wf.workspace_id = ws_id
    wf.project_id = None
    wf.definition = {
        "nodes": [],
        "edges": [{"id": edge_id, "source": "n1", "target": "n2"}],
        "variables": [],
    }

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    publish_within_tx_mock = AsyncMock()
    with _patch("app.services.agent.tools.workflow_write_tools.definition_event_service") as mock_svc:
        mock_svc.publish_within_tx = publish_within_tx_mock
        mock_svc.publish = AsyncMock()
        result = await remove_edge(
            db=db,
            ctx=ctx,
            workflow_id=str(wf.id),
            edge_id=edge_id,
        )

    assert json.loads(result) == {}
    publish_within_tx_mock.assert_awaited_once()
    call_kwargs = publish_within_tx_mock.call_args[1]
    assert call_kwargs["event_type"] == "edge_removed"
    assert call_kwargs["payload"]["edge_id"] == edge_id


@pytest.mark.asyncio
async def test_set_workflow_variables_publishes_event_within_tx():
    """Garante que set_workflow_variables chama definition_event_service.publish_within_tx."""
    from unittest.mock import patch as _patch
    from app.services.agent.context import UserContext
    from app.services.agent.tools.workflow_write_tools import set_workflow_variables

    ws_id = uuid4()
    ctx = UserContext(
        user_id=uuid4(),
        workspace_id=ws_id,
        project_id=uuid4(),
        workspace_role="MANAGER",
        project_role="EDITOR",
        organization_id=ws_id,
        organization_role=None,
    )
    wf = MagicMock()
    wf.id = uuid4()
    wf.workspace_id = ws_id
    wf.project_id = None
    wf.definition = {"nodes": [], "edges": [], "variables": []}

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = wf
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    publish_within_tx_mock = AsyncMock()
    with _patch("app.services.agent.tools.workflow_write_tools.definition_event_service") as mock_svc:
        mock_svc.publish_within_tx = publish_within_tx_mock
        mock_svc.publish = AsyncMock()
        result = await set_workflow_variables(
            db=db,
            ctx=ctx,
            workflow_id=str(wf.id),
            variables=[{"name": "token", "type": "string"}],
        )

    parsed = json.loads(result)
    assert parsed["variables_count"] == 1
    publish_within_tx_mock.assert_awaited_once()
    call_kwargs = publish_within_tx_mock.call_args[1]
    assert call_kwargs["event_type"] == "variables_updated"
    assert len(call_kwargs["payload"]["variables"]) == 1
