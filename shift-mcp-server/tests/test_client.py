"""
Testes do ShiftBackendClient.

Usamos pytest-httpx para interceptar o transport e validar que:
  - Authorization Bearer e enviado
  - respostas 2xx sao decodificadas em dict
  - respostas 4xx/5xx viram ShiftBackendError com o detail correto
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from shift_mcp_server.client import ShiftBackendClient, ShiftBackendError
from shift_mcp_server.config import MCPSettings


@pytest.fixture
def settings(monkeypatch) -> MCPSettings:
    monkeypatch.setenv("SHIFT_BACKEND_URL", "https://shift.test/api/v1")
    monkeypatch.setenv("SHIFT_API_KEY", "sk_shift_Ab3fPLAINTEXT")
    return MCPSettings()  # type: ignore[call-arg]


async def test_validate_sends_bearer_and_parses(
    httpx_mock: HTTPXMock, settings: MCPSettings
):
    httpx_mock.add_response(
        method="POST",
        url="https://shift.test/api/v1/agent-mcp/validate",
        match_headers={"Authorization": "Bearer sk_shift_Ab3fPLAINTEXT"},
        json={
            "api_key_id": "00000000-0000-0000-0000-000000000001",
            "name": "teste",
            "prefix": "sk_shift_Ab3f",
            "workspace_id": "00000000-0000-0000-0000-000000000002",
            "project_id": None,
            "max_workspace_role": "CONSULTANT",
            "max_project_role": None,
            "allowed_tools": ["list_workflows"],
            "require_human_approval": True,
            "expires_at": None,
        },
    )

    async with ShiftBackendClient(settings) as client:
        result = await client.validate()

    assert result["allowed_tools"] == ["list_workflows"]
    assert result["require_human_approval"] is True


async def test_list_tools_returns_items(
    httpx_mock: HTTPXMock, settings: MCPSettings
):
    httpx_mock.add_response(
        method="GET",
        url="https://shift.test/api/v1/agent-mcp/tools",
        json={
            "tools": [
                {
                    "name": "list_workflows",
                    "description": "lista",
                    "parameters": {"type": "object", "properties": {}},
                    "requires_approval": False,
                }
            ]
        },
    )
    async with ShiftBackendClient(settings) as client:
        tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "list_workflows"


async def test_execute_sends_approval_id_when_provided(
    httpx_mock: HTTPXMock, settings: MCPSettings
):
    httpx_mock.add_response(
        method="POST",
        url="https://shift.test/api/v1/agent-mcp/execute",
        match_json={
            "tool": "execute_workflow",
            "arguments": {"workflow_id": "abc"},
            "approval_id": "11111111-1111-1111-1111-111111111111",
        },
        json={"status": "success", "result": "disparado"},
    )
    async with ShiftBackendClient(settings) as client:
        body = await client.execute(
            tool="execute_workflow",
            arguments={"workflow_id": "abc"},
            approval_id="11111111-1111-1111-1111-111111111111",
        )
    assert body["status"] == "success"


async def test_execute_omits_approval_id_when_none(
    httpx_mock: HTTPXMock, settings: MCPSettings
):
    httpx_mock.add_response(
        method="POST",
        url="https://shift.test/api/v1/agent-mcp/execute",
        match_json={"tool": "list_workflows", "arguments": {}},
        json={"status": "success", "result": "vazio"},
    )
    async with ShiftBackendClient(settings) as client:
        await client.execute(tool="list_workflows", arguments={})


async def test_4xx_raises_backend_error_with_detail(
    httpx_mock: HTTPXMock, settings: MCPSettings
):
    httpx_mock.add_response(
        method="POST",
        url="https://shift.test/api/v1/agent-mcp/validate",
        status_code=401,
        json={"detail": "Chave invalida, revogada ou expirada."},
    )
    async with ShiftBackendClient(settings) as client:
        with pytest.raises(ShiftBackendError) as exc_info:
            await client.validate()
    assert exc_info.value.status_code == 401
    assert "revogada" in exc_info.value.detail
