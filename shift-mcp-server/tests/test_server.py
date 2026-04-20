"""
Testes do build_server — verifica que os handlers dinamicos convertem
corretamente o catalogo do backend em mcp_types.Tool e que call_tool
delega para invoke_with_approval.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# A SDK MCP importa win32api em Windows; pula o modulo inteiro se o
# ambiente nao consegue carregar a DLL (ex.: pywin32 quebrado).
mcp_types = pytest.importorskip("mcp.types", exc_type=ImportError)

from shift_mcp_server.config import MCPSettings  # noqa: E402
from shift_mcp_server.server import _to_mcp_tool, build_server  # noqa: E402


@pytest.fixture
def settings(monkeypatch) -> MCPSettings:
    monkeypatch.setenv("SHIFT_BACKEND_URL", "https://shift.test/api/v1")
    monkeypatch.setenv("SHIFT_API_KEY", "sk_shift_Ab3fPLAINTEXT")
    return MCPSettings()  # type: ignore[call-arg]


def test_to_mcp_tool_uses_defaults_for_missing_parameters():
    entry = {"name": "foo", "description": "bar"}
    tool = _to_mcp_tool(entry)
    assert isinstance(tool, mcp_types.Tool)
    assert tool.name == "foo"
    assert tool.inputSchema == {"type": "object", "properties": {}}


def test_to_mcp_tool_preserves_parameters():
    entry = {
        "name": "list_workflows",
        "description": "lista",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
    }
    tool = _to_mcp_tool(entry)
    assert tool.inputSchema["properties"]["limit"]["type"] == "integer"


async def test_build_server_registers_list_and_call_handlers(settings, monkeypatch):
    client = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=[
                {
                    "name": "list_workflows",
                    "description": "lista",
                    "parameters": {"type": "object", "properties": {}},
                    "requires_approval": False,
                }
            ]
        ),
    )

    # Interceptamos invoke_with_approval para nao depender dele aqui.
    import shift_mcp_server.server as server_mod

    invoke_mock = AsyncMock(return_value="retorno fake")
    monkeypatch.setattr(server_mod, "invoke_with_approval", invoke_mock)

    mcp_server = build_server(client, settings)  # type: ignore[arg-type]

    # list_tools handler
    list_handler = mcp_server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list")
    response = await list_handler(req)
    # ServerResult embrulha ListToolsResult
    tools = response.root.tools
    assert [t.name for t in tools] == ["list_workflows"]

    # call_tool handler
    call_handler = mcp_server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(
            name="list_workflows", arguments={"limit": 5}
        ),
    )
    call_response = await call_handler(req)
    content = call_response.root.content
    assert content[0].text == "retorno fake"
    invoke_mock.assert_awaited_once()
    assert invoke_mock.await_args.kwargs["tool"] == "list_workflows"
    assert invoke_mock.await_args.kwargs["arguments"] == {"limit": 5}
