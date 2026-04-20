"""
Testes do fluxo invoke_with_approval.

Mocamos o ShiftBackendClient. Verificamos:
  - caminho feliz sem approval
  - caminho feliz com approval (pending → approved → reexecucao)
  - rejeicao humana
  - expiracao backend-side
  - timeout do lado do MCP
  - erros HTTP
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from shift_mcp_server.approvals import invoke_with_approval
from shift_mcp_server.client import ShiftBackendError
from shift_mcp_server.config import MCPSettings


@pytest.fixture
def settings(monkeypatch) -> MCPSettings:
    monkeypatch.setenv("SHIFT_BACKEND_URL", "https://shift.test/api/v1")
    monkeypatch.setenv("SHIFT_API_KEY", "sk_shift_Ab3fPLAINTEXT")
    monkeypatch.setenv("SHIFT_MCP_APPROVAL_POLL_INTERVAL", "0.5")
    monkeypatch.setenv("SHIFT_MCP_APPROVAL_TIMEOUT", "5")
    return MCPSettings()  # type: ignore[call-arg]


def _mock_client(**overrides):
    client = SimpleNamespace()
    client.execute = AsyncMock()
    client.get_approval = AsyncMock()
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


async def test_happy_path_no_approval(settings):
    client = _mock_client()
    client.execute.return_value = {"status": "success", "result": "3 workflows"}

    result = await invoke_with_approval(
        client,  # type: ignore[arg-type]
        tool="list_workflows",
        arguments={"limit": 10},
        settings=settings,
    )

    assert result == "3 workflows"
    client.execute.assert_awaited_once()


async def test_pending_then_approved_reexecutes(settings):
    approval_id = str(uuid4())
    client = _mock_client()
    client.execute.side_effect = [
        {"status": "pending_approval", "approval_id": approval_id},
        {"status": "success", "result": "execucao disparada"},
    ]
    client.get_approval.return_value = {"status": "approved"}

    result = await invoke_with_approval(
        client,  # type: ignore[arg-type]
        tool="execute_workflow",
        arguments={"workflow_id": "abc"},
        settings=settings,
    )

    assert result == "execucao disparada"
    assert client.execute.await_count == 2
    second_call = client.execute.await_args_list[1]
    assert second_call.kwargs["approval_id"] == approval_id


async def test_rejection_returns_message(settings):
    client = _mock_client()
    client.execute.return_value = {
        "status": "pending_approval",
        "approval_id": str(uuid4()),
    }
    client.get_approval.return_value = {
        "status": "rejected",
        "rejection_reason": "nao autorizado pelo financeiro",
    }

    result = await invoke_with_approval(
        client,  # type: ignore[arg-type]
        tool="execute_workflow",
        arguments={},
        settings=settings,
    )
    assert "rejeitada" in result.lower()
    assert "financeiro" in result


async def test_expired_approval_returns_message(settings):
    client = _mock_client()
    client.execute.return_value = {
        "status": "pending_approval",
        "approval_id": str(uuid4()),
    }
    client.get_approval.return_value = {"status": "expired"}

    result = await invoke_with_approval(
        client,  # type: ignore[arg-type]
        tool="execute_workflow",
        arguments={},
        settings=settings,
    )
    assert "expirou" in result.lower()


async def test_timeout_returns_message(monkeypatch, settings):
    # Timeout curto forca estouro
    monkeypatch.setenv("SHIFT_MCP_APPROVAL_TIMEOUT", "5")
    settings = MCPSettings(  # type: ignore[call-arg]
        shift_mcp_approval_timeout=5,
        shift_mcp_approval_poll_interval=0.5,
    )

    client = _mock_client()
    client.execute.return_value = {
        "status": "pending_approval",
        "approval_id": str(uuid4()),
    }
    # get_approval sempre pending → estoura timeout
    client.get_approval.return_value = {"status": "pending"}

    # Reduz asyncio.sleep para nao esperar de verdade
    import shift_mcp_server.approvals as mod

    async def _fake_sleep(_):
        # Avanca o monotonic fake: usa time.sleep real de 0s
        pass

    # Mock asyncio.sleep para acelerar o polling
    fake_time = [0.0]

    def _fake_monotonic():
        fake_time[0] += 1.5
        return fake_time[0]

    monkeypatch.setattr(mod.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(mod.time, "monotonic", _fake_monotonic)

    result = await invoke_with_approval(
        client,  # type: ignore[arg-type]
        tool="execute_workflow",
        arguments={},
        settings=settings,
    )
    assert "timeout" in result.lower()


async def test_http_error_returns_friendly_message(settings):
    client = _mock_client()
    client.execute.side_effect = ShiftBackendError(403, "tool fora do allowlist")

    result = await invoke_with_approval(
        client,  # type: ignore[arg-type]
        tool="delete_universe",
        arguments={},
        settings=settings,
    )
    assert "HTTP 403" in result
    assert "allowlist" in result
