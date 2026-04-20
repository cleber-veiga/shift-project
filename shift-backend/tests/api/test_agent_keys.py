"""
Testes dos endpoints de chaves de API do Platform Agent.

Estrategia: mini-app FastAPI com as rotas de /agent-keys, get_db e
get_current_user sobrescritos por fixtures, authorization_service e
agent_api_key_service mocados. Nenhum banco real necessario — o foco
sao os contratos HTTP (permissoes, status codes, formato da resposta).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user, get_db
from app.api.v1.agent_keys import router
from app.core.config import settings
from app.core.security import authorization_service
from app.services.agent.api_key_service import (
    AgentApiKeyPermissionError,
    AgentApiKeyValidationError,
)


@pytest.fixture
def user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "manager@test.com"
    return u


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_key_row(
    *,
    workspace_id: uuid.UUID,
    revoked_at=None,
    allowed_tools=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="teste",
        prefix="sk_shift_Ab3f",
        workspace_id=workspace_id,
        project_id=None,
        created_by=uuid.uuid4(),
        max_workspace_role="CONSULTANT",
        max_project_role=None,
        allowed_tools=allowed_tools or ["list_workflows"],
        require_human_approval=True,
        expires_at=None,
        revoked_at=revoked_at,
        last_used_at=None,
        usage_count=0,
        created_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )


@pytest_asyncio.fixture
async def api_client(user):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _override_get_db():
        yield AsyncMock()

    async def _override_get_user():
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# 1. Flag AGENT_ENABLED desligada → 404 em tudo
# ---------------------------------------------------------------------------


async def test_404_when_flag_disabled(api_client, workspace_id):
    with patch.object(settings, "AGENT_ENABLED", False):
        r = await api_client.get(f"/api/v1/agent-keys?workspace_id={workspace_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2. POST /agent-keys exige workspace MANAGER → 403 sem
# ---------------------------------------------------------------------------


async def test_create_requires_manager(api_client, workspace_id):
    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=False),
    ):
        r = await api_client.post(
            "/api/v1/agent-keys",
            json={
                "workspace_id": str(workspace_id),
                "name": "teste",
                "max_workspace_role": "CONSULTANT",
                "allowed_tools": ["list_workflows"],
                "require_human_approval": True,
            },
        )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 3. POST /agent-keys sucesso → 201 + plaintext + entidade
# ---------------------------------------------------------------------------


async def test_create_returns_plaintext_and_prefix(api_client, workspace_id):
    key_row = _make_key_row(workspace_id=workspace_id)
    plaintext = "sk_shift_Ab3f" + "X" * 40

    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.create",
        AsyncMock(return_value=(key_row, plaintext)),
    ):
        r = await api_client.post(
            "/api/v1/agent-keys",
            json={
                "workspace_id": str(workspace_id),
                "name": "teste",
                "max_workspace_role": "CONSULTANT",
                "allowed_tools": ["list_workflows"],
                "require_human_approval": True,
            },
        )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key"] == plaintext
    assert "warning" in body
    assert body["key"]["prefix"] == key_row.prefix
    assert "key_hash" not in body["key"]


# ---------------------------------------------------------------------------
# 4. Validacao de tools desconhecidas → 400
# ---------------------------------------------------------------------------


async def test_create_rejects_unknown_tools(api_client, workspace_id):
    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.create",
        AsyncMock(side_effect=AgentApiKeyValidationError("Tools desconhecidas: foo")),
    ):
        r = await api_client.post(
            "/api/v1/agent-keys",
            json={
                "workspace_id": str(workspace_id),
                "name": "teste",
                "max_workspace_role": "CONSULTANT",
                "allowed_tools": ["foo"],
                "require_human_approval": True,
            },
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 5. Criador tentando conceder role maior → 403
# ---------------------------------------------------------------------------


async def test_create_rejects_role_escalation(api_client, workspace_id):
    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.create",
        AsyncMock(
            side_effect=AgentApiKeyPermissionError("role maior que a propria")
        ),
    ):
        r = await api_client.post(
            "/api/v1/agent-keys",
            json={
                "workspace_id": str(workspace_id),
                "name": "teste",
                "max_workspace_role": "MANAGER",
                "allowed_tools": ["list_workflows"],
                "require_human_approval": True,
            },
        )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 6. GET /agent-keys → oculta hash e retorna total
# ---------------------------------------------------------------------------


async def test_list_hides_hash(api_client, workspace_id):
    key_active = _make_key_row(workspace_id=workspace_id)
    key_revoked = _make_key_row(
        workspace_id=workspace_id,
        revoked_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )

    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.list",
        AsyncMock(return_value=([key_active, key_revoked], 2)),
    ):
        r = await api_client.get(
            f"/api/v1/agent-keys?workspace_id={workspace_id}"
        )

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert "key_hash" not in item
        assert "api_key" not in item


# ---------------------------------------------------------------------------
# 7. POST /agent-keys/{id}/revoke → 200 com revoked_at preenchido
# ---------------------------------------------------------------------------


async def test_revoke_prevents_future_validation(api_client, workspace_id):
    import datetime as _dt

    revoked_key = _make_key_row(
        workspace_id=workspace_id,
        revoked_at=_dt.datetime.now(_dt.timezone.utc),
    )
    active_key = _make_key_row(workspace_id=workspace_id)

    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.get",
        AsyncMock(return_value=active_key),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.revoke",
        AsyncMock(return_value=revoked_key),
    ):
        r = await api_client.post(
            f"/api/v1/agent-keys/{active_key.id}/revoke"
        )

    assert r.status_code == 200
    assert r.json()["revoked_at"] is not None


async def test_revoke_404_when_not_found(api_client):
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_keys.agent_api_key_service.get",
        AsyncMock(return_value=None),
    ):
        r = await api_client.post(
            f"/api/v1/agent-keys/{uuid.uuid4()}/revoke"
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 8. DELETE /agent-keys/{id} → 204
# ---------------------------------------------------------------------------


async def test_delete_returns_204(api_client, workspace_id):
    key = _make_key_row(workspace_id=workspace_id)

    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=True),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.get",
        AsyncMock(return_value=key),
    ), patch(
        "app.api.v1.agent_keys.agent_api_key_service.delete",
        AsyncMock(return_value=None),
    ):
        r = await api_client.delete(f"/api/v1/agent-keys/{key.id}")

    assert r.status_code == 204


# ---------------------------------------------------------------------------
# 9. Revoke/delete sem MANAGER no workspace → 403
# ---------------------------------------------------------------------------


async def test_cannot_revoke_without_manager(api_client, workspace_id):
    key = _make_key_row(workspace_id=workspace_id)
    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent_keys.agent_api_key_service.get",
        AsyncMock(return_value=key),
    ), patch.object(
        authorization_service,
        "has_permission",
        AsyncMock(return_value=False),
    ):
        r = await api_client.post(f"/api/v1/agent-keys/{key.id}/revoke")
    assert r.status_code == 403
