"""
Testes unitarios do MCPBridgeService.

Focamos na orquestracao: thread sintetica, approval flow, audit log,
mensagens de erro. As funcoes externas (create_approval, write_audit_log,
ensure_thread, execute_tool) sao mocadas — elas tem testes proprios.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.agent.mcp_bridge_service import (
    MCPApprovalInvalidError,
    MCPApprovalRequiredError,
    MCPBridgeError,
    MCPBridgeService,
    MCPToolNotAllowedError,
    _mcp_thread_id_for_key,
    build_user_context,
    mcp_bridge_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_api_key(
    *,
    allowed_tools: list[str] | None = None,
    require_human_approval: bool = True,
    max_workspace_role: str = "CONSULTANT",
    max_project_role: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="teste",
        prefix="sk_shift_Ab3f",
        created_by=uuid4(),
        workspace_id=uuid4(),
        project_id=None,
        max_workspace_role=max_workspace_role,
        max_project_role=max_project_role,
        allowed_tools=allowed_tools or ["list_workflows"],
        require_human_approval=require_human_approval,
    )


@pytest.fixture
def service() -> MCPBridgeService:
    return MCPBridgeService()


@pytest.fixture
def db():
    sess = AsyncMock()
    sess.execute = AsyncMock()
    sess.add = MagicMock()
    sess.flush = AsyncMock()
    sess.refresh = AsyncMock()
    sess.commit = AsyncMock()
    sess.get = AsyncMock()
    return sess


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


def test_thread_id_is_deterministic_per_key():
    api_key_id = uuid4()
    a = _mcp_thread_id_for_key(api_key_id)
    b = _mcp_thread_id_for_key(api_key_id)
    c = _mcp_thread_id_for_key(uuid4())
    assert a == b
    assert a != c
    assert isinstance(a, UUID)


def test_build_user_context_uses_capped_roles():
    key = _make_api_key(max_workspace_role="CONSULTANT", max_project_role=None)
    ctx = build_user_context(key)
    assert ctx.user_id == key.created_by
    assert ctx.workspace_id == key.workspace_id
    assert ctx.workspace_role == "CONSULTANT"
    assert ctx.project_role is None
    assert ctx.organization_role is None


# ---------------------------------------------------------------------------
# execute() — allowlist
# ---------------------------------------------------------------------------


async def test_execute_rejects_unknown_tool(service, db):
    api_key = _make_api_key()
    with pytest.raises(MCPBridgeError):
        await service.execute(
            db,
            api_key=api_key,
            tool_name="nao_existe",
            arguments={},
            approval_id=None,
        )


async def test_execute_rejects_tool_outside_allowlist(service, db):
    api_key = _make_api_key(allowed_tools=["list_workflows"])
    with pytest.raises(MCPToolNotAllowedError):
        await service.execute(
            db,
            api_key=api_key,
            tool_name="get_workflow",
            arguments={"workflow_id": str(uuid4())},
            approval_id=None,
        )


async def test_execute_allows_wildcard(service, db):
    api_key = _make_api_key(allowed_tools=["*"])

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.agent.mcp_bridge_service.execute_tool",
        AsyncMock(return_value="ok"),
    ), patch(
        "app.services.agent.mcp_bridge_service.write_audit_log",
        AsyncMock(return_value=uuid4()),
    ):
        result = await service.execute(
            db,
            api_key=api_key,
            tool_name="get_workflow",
            arguments={"workflow_id": str(uuid4())},
            approval_id=None,
        )
    assert result.status == "success"
    assert result.result == "ok"


# ---------------------------------------------------------------------------
# execute() — caminho feliz read-only
# ---------------------------------------------------------------------------


async def test_execute_readonly_writes_audit_with_mcp_metadata(service, db):
    api_key = _make_api_key(allowed_tools=["list_workflows"])
    audit_id = uuid4()

    captured: dict = {}

    async def _fake_audit(_db, **kwargs):
        captured.update(kwargs)
        return audit_id

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.agent.mcp_bridge_service.execute_tool",
        AsyncMock(return_value="3 workflows encontrados."),
    ), patch(
        "app.services.agent.mcp_bridge_service.write_audit_log",
        side_effect=_fake_audit,
    ):
        result = await service.execute(
            db,
            api_key=api_key,
            tool_name="list_workflows",
            arguments={"limit": 10},
            approval_id=None,
        )

    assert result.status == "success"
    assert result.audit_log_id == audit_id
    assert captured["status"] == "success"
    assert captured["approval_id"] is None
    meta = captured["log_metadata"]
    assert meta["source"] == "mcp"
    assert meta["api_key_id"] == str(api_key.id)
    assert meta["api_key_prefix"] == api_key.prefix
    assert captured["user_id"] == api_key.created_by
    assert captured["tool_name"] == "list_workflows"


# ---------------------------------------------------------------------------
# execute() — approval flow
# ---------------------------------------------------------------------------


async def test_execute_destructive_without_approval_creates_approval(service, db):
    api_key = _make_api_key(
        allowed_tools=["execute_workflow"], require_human_approval=True
    )
    new_approval_id = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    approval_row = SimpleNamespace(id=new_approval_id, expires_at=expires)

    db.get = AsyncMock(return_value=approval_row)

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.agent.mcp_bridge_service.create_approval",
        AsyncMock(return_value=new_approval_id),
    ), patch(
        "app.services.agent.mcp_bridge_service.execute_tool",
        AsyncMock(return_value="nao deveria rodar"),
    ) as exec_mock, patch(
        "app.services.agent.mcp_bridge_service.write_audit_log",
        AsyncMock(return_value=uuid4()),
    ) as audit_mock:
        with pytest.raises(MCPApprovalRequiredError) as exc_info:
            await service.execute(
                db,
                api_key=api_key,
                tool_name="execute_workflow",
                arguments={"workflow_id": str(uuid4())},
                approval_id=None,
            )

    assert exc_info.value.approval_id == new_approval_id
    assert exc_info.value.expires_at == expires
    exec_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()


async def test_execute_destructive_respects_key_opt_out(service, db):
    """require_human_approval=False → executa sem criar approval."""
    api_key = _make_api_key(
        allowed_tools=["execute_workflow"], require_human_approval=False
    )

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.agent.mcp_bridge_service.create_approval",
        AsyncMock(return_value=uuid4()),
    ) as approval_mock, patch(
        "app.services.agent.mcp_bridge_service.execute_tool",
        AsyncMock(return_value="executado."),
    ) as exec_mock, patch(
        "app.services.agent.mcp_bridge_service.write_audit_log",
        AsyncMock(return_value=uuid4()),
    ):
        result = await service.execute(
            db,
            api_key=api_key,
            tool_name="execute_workflow",
            arguments={"workflow_id": str(uuid4())},
            approval_id=None,
        )

    assert result.status == "success"
    approval_mock.assert_not_awaited()
    exec_mock.assert_awaited_once()


async def test_execute_with_valid_approval_id_runs_and_links_audit(service, db):
    api_key = _make_api_key(
        allowed_tools=["execute_workflow"], require_human_approval=True
    )
    thread_id = _mcp_thread_id_for_key(api_key.id)
    approval_id = uuid4()
    wf_id = uuid4()
    arguments = {"workflow_id": str(wf_id)}
    approval_row = SimpleNamespace(
        id=approval_id,
        thread_id=thread_id,
        status="approved",
        proposed_plan={
            "source": "mcp",
            "api_key_id": str(api_key.id),
            "tool": "execute_workflow",
            "arguments": arguments,
        },
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=approval_row)
    db.execute = AsyncMock(return_value=select_result)

    captured: dict = {}

    async def _fake_audit(_db, **kwargs):
        captured.update(kwargs)
        return uuid4()

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.agent.mcp_bridge_service.execute_tool",
        AsyncMock(return_value="execucao disparada."),
    ), patch(
        "app.services.agent.mcp_bridge_service.write_audit_log",
        side_effect=_fake_audit,
    ):
        result = await service.execute(
            db,
            api_key=api_key,
            tool_name="execute_workflow",
            arguments=arguments,
            approval_id=approval_id,
        )

    assert result.status == "success"
    assert captured["approval_id"] == approval_id


async def test_execute_rejects_approval_not_approved(service, db):
    api_key = _make_api_key(
        allowed_tools=["execute_workflow"], require_human_approval=True
    )
    thread_id = _mcp_thread_id_for_key(api_key.id)
    approval_id = uuid4()
    approval_row = SimpleNamespace(
        id=approval_id,
        thread_id=thread_id,
        status="pending",
        proposed_plan={"tool": "execute_workflow", "arguments": {}},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=approval_row)
    db.execute = AsyncMock(return_value=select_result)

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(MCPApprovalInvalidError):
            await service.execute(
                db,
                api_key=api_key,
                tool_name="execute_workflow",
                arguments={},
                approval_id=approval_id,
            )


async def test_execute_rejects_approval_with_mismatched_args(service, db):
    api_key = _make_api_key(
        allowed_tools=["execute_workflow"], require_human_approval=True
    )
    thread_id = _mcp_thread_id_for_key(api_key.id)
    approval_id = uuid4()
    approval_row = SimpleNamespace(
        id=approval_id,
        thread_id=thread_id,
        status="approved",
        proposed_plan={
            "tool": "execute_workflow",
            "arguments": {"workflow_id": "original-id"},
        },
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=approval_row)
    db.execute = AsyncMock(return_value=select_result)

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(MCPApprovalInvalidError):
            await service.execute(
                db,
                api_key=api_key,
                tool_name="execute_workflow",
                arguments={"workflow_id": "adulterado"},  # != approved plan
                approval_id=approval_id,
            )


# ---------------------------------------------------------------------------
# execute() — erro na tool
# ---------------------------------------------------------------------------


async def test_execute_records_error_when_tool_raises(service, db):
    api_key = _make_api_key(allowed_tools=["list_workflows"])
    captured: dict = {}

    async def _fake_audit(_db, **kwargs):
        captured.update(kwargs)
        return uuid4()

    with patch(
        "app.services.agent.mcp_bridge_service.ensure_thread",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.agent.mcp_bridge_service.execute_tool",
        AsyncMock(side_effect=RuntimeError("boom")),
    ), patch(
        "app.services.agent.mcp_bridge_service.write_audit_log",
        side_effect=_fake_audit,
    ):
        result = await service.execute(
            db,
            api_key=api_key,
            tool_name="list_workflows",
            arguments={},
            approval_id=None,
        )

    assert result.status == "error"
    assert "boom" in result.result
    assert captured["status"] == "error"
    assert captured["error_message"] == "boom"
