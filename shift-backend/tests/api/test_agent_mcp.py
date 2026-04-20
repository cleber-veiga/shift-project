"""
Testes dos endpoints /agent-mcp/* (bridge MCP).

Estrategia: mini-FastAPI com o router, get_db sobrescrito,
agent_api_key_service.validate e mcp_bridge_service.execute/get_approval
mocados. Cobrimos contratos HTTP (auth, 401/403/400/202/200),
serializacao de tools e polling de approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_db
from app.api.v1.agent_mcp import router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.services.agent.mcp_bridge_service import (
    MCPApprovalInvalidError,
    MCPApprovalRequiredError,
    MCPBridgeError,
    MCPExecutionResult,
    MCPToolNotAllowedError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_api_key(
    *,
    allowed_tools: list[str] | None = None,
    require_human_approval: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="teste",
        prefix="sk_shift_Ab3f",
        created_by=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=None,
        max_workspace_role="CONSULTANT",
        max_project_role=None,
        allowed_tools=allowed_tools or ["list_workflows", "execute_workflow"],
        require_human_approval=require_human_approval,
        expires_at=None,
    )


@pytest_asyncio.fixture
async def api_client():
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1")

    async def _override_get_db():
        yield AsyncMock(commit=AsyncMock())

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# 1. AGENT_ENABLED=False → 404 em tudo (sem precisar de token)
# ---------------------------------------------------------------------------


async def test_404_when_flag_disabled(api_client):
    with patch.object(settings, "AGENT_ENABLED", False):
        r = await api_client.post(
            "/api/v1/agent-mcp/validate",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2. Sem Authorization → 401
# ---------------------------------------------------------------------------


async def test_401_without_bearer(api_client):
    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.post("/api/v1/agent-mcp/validate")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 3. Bearer invalido → 401
# ---------------------------------------------------------------------------


async def test_401_when_key_invalid(api_client):
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=None),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/validate",
            headers={"Authorization": "Bearer sk_shift_NopeNopeNopeNopeNope"},
        )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 4. /validate sucesso → 200 com metadados da chave
# ---------------------------------------------------------------------------


async def test_validate_returns_key_metadata(api_client):
    key = _make_api_key()
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/validate",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key_id"] == str(key.id)
    assert body["workspace_id"] == str(key.workspace_id)
    assert body["allowed_tools"] == key.allowed_tools
    assert body["require_human_approval"] is True
    # Hash e chave nunca devem vazar
    assert "key_hash" not in body
    assert "api_key" not in body


# ---------------------------------------------------------------------------
# 5. /tools filtra pelo allowed_tools
# ---------------------------------------------------------------------------


async def test_tools_lists_only_allowed(api_client):
    key = _make_api_key(allowed_tools=["list_workflows"])
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ):
        r = await api_client.get(
            "/api/v1/agent-mcp/tools",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
        )

    assert r.status_code == 200
    tools = r.json()["tools"]
    names = [t["name"] for t in tools]
    assert names == ["list_workflows"]
    assert tools[0]["requires_approval"] is False
    assert "parameters" in tools[0]


async def test_tools_with_wildcard_returns_all(api_client):
    key = _make_api_key(allowed_tools=["*"])
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ):
        r = await api_client.get(
            "/api/v1/agent-mcp/tools",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
        )
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    # Sanity: pelo menos algumas tools conhecidas estao presentes
    assert {"list_workflows", "execute_workflow", "list_projects"} <= names


# ---------------------------------------------------------------------------
# 6. /execute read-only → 200 success
# ---------------------------------------------------------------------------


async def test_execute_readonly_returns_success(api_client):
    key = _make_api_key(allowed_tools=["list_workflows"])
    audit_id = uuid.uuid4()
    exec_result = MCPExecutionResult(
        status="success",
        result="3 workflows",
        audit_log_id=audit_id,
        duration_ms=42,
    )

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.mcp_bridge_service.execute",
        AsyncMock(return_value=exec_result),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/execute",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
            json={"tool": "list_workflows", "arguments": {"limit": 10}},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["result"] == "3 workflows"
    assert body["audit_log_id"] == str(audit_id)
    assert body["duration_ms"] == 42


# ---------------------------------------------------------------------------
# 7. /execute tool fora do allowed_tools → 403
# ---------------------------------------------------------------------------


async def test_execute_tool_not_allowed_returns_403(api_client):
    key = _make_api_key(allowed_tools=["list_workflows"])

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.mcp_bridge_service.execute",
        AsyncMock(side_effect=MCPToolNotAllowedError("fora do allowlist")),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/execute",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
            json={"tool": "list_workflows", "arguments": {}},
        )

    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 8. /execute destrutivo sem approval → 202-like (200 + pending_approval)
# ---------------------------------------------------------------------------


async def test_execute_destructive_without_approval_returns_pending(api_client):
    key = _make_api_key(allowed_tools=["execute_workflow"])
    approval_id = uuid.uuid4()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.agent_budget_service.check_destructive_budget",
        AsyncMock(return_value=SimpleNamespace(ok=True, reason=None, retry_after_seconds=None)),
    ), patch(
        "app.api.v1.agent_mcp.mcp_bridge_service.execute",
        AsyncMock(
            side_effect=MCPApprovalRequiredError(approval_id=approval_id, expires_at=expires)
        ),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/execute",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
            json={
                "tool": "execute_workflow",
                "arguments": {"workflow_id": str(uuid.uuid4())},
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_approval"
    assert body["approval_id"] == str(approval_id)
    assert body["approval_expires_at"] is not None


# ---------------------------------------------------------------------------
# 9. /execute destrutivo, budget esgotado → 429 + Retry-After
# ---------------------------------------------------------------------------


async def test_execute_destructive_budget_exhausted_returns_429(api_client):
    key = _make_api_key(allowed_tools=["execute_workflow"])

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.agent_budget_service.check_destructive_budget",
        AsyncMock(
            return_value=SimpleNamespace(
                ok=False, reason="limite excedido", retry_after_seconds=120
            )
        ),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/execute",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
            json={
                "tool": "execute_workflow",
                "arguments": {"workflow_id": str(uuid.uuid4())},
            },
        )

    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "120"


# ---------------------------------------------------------------------------
# 10. /execute com approval_id invalido → 400
# ---------------------------------------------------------------------------


async def test_execute_rejects_invalid_approval(api_client):
    key = _make_api_key(allowed_tools=["execute_workflow"])
    approval_id = uuid.uuid4()

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.agent_budget_service.check_destructive_budget",
        AsyncMock(return_value=SimpleNamespace(ok=True, reason=None, retry_after_seconds=None)),
    ), patch(
        "app.api.v1.agent_mcp.mcp_bridge_service.execute",
        AsyncMock(side_effect=MCPApprovalInvalidError("approval nao aprovada")),
    ):
        r = await api_client.post(
            "/api/v1/agent-mcp/execute",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
            json={
                "tool": "execute_workflow",
                "arguments": {"workflow_id": str(uuid.uuid4())},
                "approval_id": str(approval_id),
            },
        )

    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 11. /approvals/{id} → 200 com status
# ---------------------------------------------------------------------------


async def test_approval_status_returns_200(api_client):
    key = _make_api_key()
    approval_id = uuid.uuid4()
    approval = SimpleNamespace(
        id=approval_id,
        status="approved",
        proposed_plan={"tool": "execute_workflow", "arguments": {}},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        decided_at=datetime.now(timezone.utc),
        rejection_reason=None,
    )

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.mcp_bridge_service.get_approval",
        AsyncMock(return_value=approval),
    ):
        r = await api_client.get(
            f"/api/v1/agent-mcp/approvals/{approval_id}",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(approval_id)
    assert body["status"] == "approved"


async def test_approval_status_404_when_not_found(api_client):
    key = _make_api_key()
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_mcp.agent_api_key_service.validate",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_mcp.mcp_bridge_service.get_approval",
        AsyncMock(side_effect=MCPBridgeError("nao encontrada")),
    ):
        r = await api_client.get(
            f"/api/v1/agent-mcp/approvals/{uuid.uuid4()}",
            headers={"Authorization": "Bearer sk_shift_Ab3fXXXXXXXXXXXXXXXXXXXXXXX"},
        )
    assert r.status_code == 404
