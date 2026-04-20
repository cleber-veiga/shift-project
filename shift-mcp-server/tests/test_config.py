"""Testes de MCPSettings — parsing de env e validacao."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shift_mcp_server.config import MCPSettings


def test_loads_from_env(monkeypatch):
    monkeypatch.setenv("SHIFT_BACKEND_URL", "https://shift.example.com/api/v1")
    monkeypatch.setenv("SHIFT_API_KEY", "sk_shift_Ab3fXXXXXXXXXX")

    settings = MCPSettings()  # type: ignore[call-arg]
    assert str(settings.shift_backend_url).rstrip("/") == "https://shift.example.com/api/v1"
    assert settings.shift_api_key.get_secret_value() == "sk_shift_Ab3fXXXXXXXXXX"
    # defaults
    assert settings.shift_mcp_transport == "stdio"
    assert settings.shift_mcp_host == "127.0.0.1"
    assert settings.shift_mcp_port == 8765
    assert settings.shift_mcp_approval_poll_interval == 2.0


def test_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("SHIFT_BACKEND_URL", raising=False)
    monkeypatch.delenv("SHIFT_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        MCPSettings()  # type: ignore[call-arg]


def test_transport_enum_rejects_invalid(monkeypatch):
    monkeypatch.setenv("SHIFT_BACKEND_URL", "https://shift.example.com/api/v1")
    monkeypatch.setenv("SHIFT_API_KEY", "sk_shift_Ab3fXXXXXXXXXX")
    monkeypatch.setenv("SHIFT_MCP_TRANSPORT", "websocket")
    with pytest.raises(ValidationError):
        MCPSettings()  # type: ignore[call-arg]


def test_approval_timeout_bounds(monkeypatch):
    monkeypatch.setenv("SHIFT_BACKEND_URL", "https://shift.example.com/api/v1")
    monkeypatch.setenv("SHIFT_API_KEY", "sk_shift_Ab3fXXXXXXXXXX")
    monkeypatch.setenv("SHIFT_MCP_APPROVAL_POLL_INTERVAL", "0.1")  # abaixo do ge=0.5
    with pytest.raises(ValidationError):
        MCPSettings()  # type: ignore[call-arg]
