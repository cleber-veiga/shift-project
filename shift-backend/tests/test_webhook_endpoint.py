"""
Testes dos endpoints do no Webhook.

Cobre:
- resolve_webhook (UUID do workflow e path custom; 404)
- autenticacao (none/header/basic/jwt) — paths de aceitacao e rejeicao
- rota de producao ``/api/v1/webhook/{path}``: estado do workflow
  (draft vs. published), HTTP method matching (405), respond modes
  (immediately, on_finish, using_respond_node -> 501)
- rota de teste ``/api/v1/webhook-test/{path}``: upsert de capture,
  nao dispara workflow, funciona inclusive em draft
- ``/workflows/{id}/webhook/listen``: captura ja existente retorna
  imediatamente, timeout retorna 408, captura chegando durante a espera
  acorda o cliente

Estrategia (igual aos demais testes de endpoint):
monta um mini-app FastAPI com as rotas reais e substitui ``get_db``
por uma sessao SQLite in-memory. Tipos Postgres (JSONB, UUID) ganham
compiladores SQLite para que ``create_all`` funcione. Como o codigo
de producao usa ``pg_insert().on_conflict_do_update()`` para o upsert
da captura, sobrescrevemos ``webhook_service.upsert_test_capture``
com uma variante portavel durante os testes.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


# ---------------------------------------------------------------------------
# Compatibilidade de tipos Postgres -> SQLite (uso somente em teste)
# ---------------------------------------------------------------------------

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "CHAR(36)"


# Imports AFTER the compiler registrations.
from app.api.dependencies import get_db  # noqa: E402
from app.api.v1 import webhooks_admin as webhooks_admin_module  # noqa: E402
from app.api.v1.endpoints import webhooks as webhooks_module  # noqa: E402
from app.core.security import require_permission  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.workflow import (  # noqa: E402
    WebhookTestCapture,
    Workflow,
)
from app.schemas.workflow import ExecutionResponse  # noqa: E402
from app.services import webhook_service  # noqa: E402


# ---------------------------------------------------------------------------
# Upsert portavel (SQLite): substitui a versao Postgres somente em teste.
# ---------------------------------------------------------------------------

async def _portable_upsert_test_capture(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_id: str,
    *,
    method: str,
    headers: dict[str, str],
    query_params: dict[str, Any],
    body: Any,
    raw_b64: str | None,
) -> WebhookTestCapture:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=webhook_service.CAPTURE_TTL_MINUTES)

    # SELECT + UPDATE/INSERT manual
    existing = await db.execute(
        select(WebhookTestCapture).where(
            WebhookTestCapture.workflow_id == workflow_id,
            WebhookTestCapture.node_id == node_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        row.method = method
        row.headers = headers
        row.query_params = query_params
        row.body = body
        row.raw_body_b64 = raw_b64
        row.captured_at = now
        row.expires_at = expires_at
    else:
        row = WebhookTestCapture(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            node_id=node_id,
            method=method,
            headers=headers,
            query_params=query_params,
            body=body,
            raw_body_b64=raw_b64,
            captured_at=now,
            expires_at=expires_at,
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    webhook_service.notify_capture(workflow_id, node_id)
    return row


async def _portable_delete_captures(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_id: str,
) -> int:
    result = await db.execute(
        delete(WebhookTestCapture).where(
            WebhookTestCapture.workflow_id == workflow_id,
            WebhookTestCapture.node_id == node_id,
        )
    )
    await db.commit()
    webhook_service.clear_event(workflow_id, node_id)
    return int(result.rowcount or 0)


@pytest.fixture(autouse=True)
def _patch_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        webhook_service, "upsert_test_capture", _portable_upsert_test_capture
    )
    monkeypatch.setattr(
        webhook_service, "delete_captures", _portable_delete_captures
    )


# ---------------------------------------------------------------------------
# Fixtures: engine, session, app com dependency overrides
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Remove defaults especificos do Postgres (::jsonb, gen_random_uuid())
    # para permitir create_all no SQLite.
    _strip_pg_defaults()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


_STRIPPED = False


def _strip_pg_defaults() -> None:
    """Remove server_default com sintaxe Postgres dos modelos (idempotente)."""
    global _STRIPPED
    if _STRIPPED:
        return
    for table in Base.metadata.tables.values():
        for col in table.columns:
            sd = getattr(col, "server_default", None)
            if sd is None:
                continue
            text_repr = str(getattr(sd, "arg", sd))
            if "::jsonb" in text_repr or "gen_random_uuid" in text_repr:
                col.server_default = None
    _STRIPPED = True


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


class _FakeWorkflowService:
    """Stub de ``workflow_service`` que registra as chamadas a ``run``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.on_finish_output: dict[str, Any] | None = None
        self.on_finish_delay: float = 0.0

    async def run(
        self,
        *,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        triggered_by: str = "manual",
        input_data: dict[str, Any] | None = None,
        event_sink: Any | None = None,
        mode: str | None = None,
        wait: bool = False,
        target_node_id: str | None = None,
    ) -> ExecutionResponse:
        self.calls.append(
            {
                "workflow_id": workflow_id,
                "triggered_by": triggered_by,
                "input_data": input_data,
                "mode": mode,
                "wait": wait,
            }
        )
        if wait and event_sink is not None:
            if self.on_finish_delay:
                await asyncio.sleep(self.on_finish_delay)
            await event_sink(
                {
                    "type": "execution_complete",
                    "output": self.on_finish_output or {"data": [{"ok": True}]},
                }
            )
        return ExecutionResponse(execution_id=uuid.uuid4(), status="PENDING")


@pytest_asyncio.fixture
async def fake_workflow_service(monkeypatch: pytest.MonkeyPatch) -> _FakeWorkflowService:
    fake = _FakeWorkflowService()
    monkeypatch.setattr(webhooks_module, "workflow_service", fake)
    return fake


@pytest_asyncio.fixture
async def api_client(
    session_factory,
    fake_workflow_service: _FakeWorkflowService,
):
    app = FastAPI()

    async def _allow() -> None:
        return None

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Rotas publicas de recepcao de webhook (sem auth)
    app.include_router(webhooks_module.router, prefix="/api/v1")
    # Rotas autenticadas de apoio a UI
    app.include_router(webhooks_admin_module.router, prefix="/api/v1")

    app.dependency_overrides[get_db] = _override_get_db
    # Bypass de require_permission (identico a test_workflow_executions_api).
    for route in app.router.routes:
        if hasattr(route, "dependant"):
            for sub in route.dependant.dependencies:
                if sub.call is not None and getattr(
                    sub.call, "__qualname__", ""
                ).startswith("require_permission"):
                    app.dependency_overrides[sub.call] = _allow

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers de construcao
# ---------------------------------------------------------------------------

def _webhook_node(
    node_id: str = "node-webhook-1",
    *,
    http_method: str = "POST",
    path: str | None = None,
    authentication: dict[str, Any] | None = None,
    respond_mode: str = "immediately",
    response_code: int = 200,
    response_data: str = "first_entry_json",
    raw_body: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": "webhook",
        "http_method": http_method,
        "respond_mode": respond_mode,
        "response_code": response_code,
        "response_data": response_data,
        "raw_body": raw_body,
    }
    if path is not None:
        data["path"] = path
    if authentication is not None:
        data["authentication"] = authentication
    return {"id": node_id, "type": "webhook", "data": data}


async def _make_workflow(
    db: AsyncSession,
    *,
    node: dict[str, Any] | None = None,
    status: str = "published",
    is_published: bool = True,
) -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        name="wf",
        workspace_id=uuid.uuid4(),
        status=status,
        is_published=is_published,
        definition={"nodes": [node] if node is not None else [], "edges": []},
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# Testes de resolve_webhook (unidade, sem endpoint)
# ---------------------------------------------------------------------------

class TestResolveWebhook:
    async def test_resolves_by_uuid(self, db: AsyncSession) -> None:
        wf = await _make_workflow(db, node=_webhook_node("n1"))
        resolved = await webhook_service.resolve_webhook(db, str(wf.id))
        assert resolved is not None
        workflow, node_id, cfg = resolved
        assert workflow.id == wf.id
        assert node_id == "n1"
        assert cfg["type"] == "webhook"

    async def test_resolves_by_custom_path(self, db: AsyncSession) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node("n1", path="incoming/orders")
        )
        resolved = await webhook_service.resolve_webhook(db, "incoming/orders")
        assert resolved is not None
        workflow, node_id, cfg = resolved
        assert workflow.id == wf.id
        assert node_id == "n1"
        assert cfg["path"] == "incoming/orders"

    async def test_unknown_path_returns_none(self, db: AsyncSession) -> None:
        await _make_workflow(db, node=_webhook_node("n1", path="kept"))
        resolved = await webhook_service.resolve_webhook(db, "does/not/exist")
        assert resolved is None

    async def test_workflow_without_webhook_node(self, db: AsyncSession) -> None:
        wf = await _make_workflow(db, node=None)
        resolved = await webhook_service.resolve_webhook(db, str(wf.id))
        assert resolved is None


# ---------------------------------------------------------------------------
# Testes de autenticacao (unidade)
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        # headers do Starlette sao case-insensitive — simulamos via lower-casing.
        self.headers = {k.lower(): v for k, v in headers.items()}


def _fake_request(headers: dict[str, str]) -> Any:
    class _H:
        def __init__(self, h: dict[str, str]) -> None:
            self._h = {k.lower(): v for k, v in h.items()}

        def get(self, key: str, default: Any = None) -> Any:
            return self._h.get(key.lower(), default)

    class _R:
        def __init__(self) -> None:
            self.headers = _H(headers)

    return _R()


class TestAuthenticateWebhook:
    def test_none_always_passes(self) -> None:
        assert webhook_service.authenticate_webhook(_fake_request({}), None) is None
        assert (
            webhook_service.authenticate_webhook(
                _fake_request({}), {"type": "none"}
            )
            is None
        )

    def test_header_ok(self) -> None:
        cfg = {"type": "header", "header_name": "X-Api-Key", "header_value": "abc"}
        req = _fake_request({"X-Api-Key": "abc"})
        assert webhook_service.authenticate_webhook(req, cfg) is None

    def test_header_wrong_value(self) -> None:
        cfg = {"type": "header", "header_name": "X-Api-Key", "header_value": "abc"}
        req = _fake_request({"X-Api-Key": "WRONG"})
        assert webhook_service.authenticate_webhook(req, cfg) is not None

    def test_header_missing(self) -> None:
        cfg = {"type": "header", "header_name": "X-Api-Key", "header_value": "abc"}
        assert webhook_service.authenticate_webhook(_fake_request({}), cfg) is not None

    def test_basic_ok(self) -> None:
        cfg = {"type": "basic", "username": "u", "password": "p"}
        token = base64.b64encode(b"u:p").decode("ascii")
        req = _fake_request({"authorization": f"Basic {token}"})
        assert webhook_service.authenticate_webhook(req, cfg) is None

    def test_basic_wrong_password(self) -> None:
        cfg = {"type": "basic", "username": "u", "password": "p"}
        token = base64.b64encode(b"u:WRONG").decode("ascii")
        req = _fake_request({"authorization": f"Basic {token}"})
        assert webhook_service.authenticate_webhook(req, cfg) is not None

    def test_jwt_ok(self) -> None:
        secret = "shh"
        token = jwt.encode({"sub": "x"}, secret, algorithm="HS256")
        cfg = {"type": "jwt", "jwt_secret": secret, "jwt_algorithm": "HS256"}
        req = _fake_request({"authorization": f"Bearer {token}"})
        assert webhook_service.authenticate_webhook(req, cfg) is None

    def test_jwt_invalid_token(self) -> None:
        cfg = {"type": "jwt", "jwt_secret": "shh", "jwt_algorithm": "HS256"}
        req = _fake_request({"authorization": "Bearer not-a-jwt"})
        assert webhook_service.authenticate_webhook(req, cfg) is not None

    def test_jwt_missing_token(self) -> None:
        cfg = {"type": "jwt", "jwt_secret": "shh", "jwt_algorithm": "HS256"}
        assert webhook_service.authenticate_webhook(_fake_request({}), cfg) is not None


# ---------------------------------------------------------------------------
# Testes da rota de producao /api/v1/webhook/{path}
# ---------------------------------------------------------------------------

class TestProductionWebhook:
    async def test_published_post_dispatches(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node(http_method="POST"))
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={"hello": "world"})
        assert r.status_code == 200
        assert len(fake_workflow_service.calls) == 1
        call = fake_workflow_service.calls[0]
        assert call["workflow_id"] == wf.id
        assert call["triggered_by"] == "webhook"
        assert call["wait"] is False
        assert call["input_data"]["method"] == "POST"
        assert call["input_data"]["body"] == {"hello": "world"}

    async def test_draft_returns_404(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node(), status="draft", is_published=False
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 404
        assert fake_workflow_service.calls == []

    async def test_published_but_is_published_false_returns_404(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node(), status="published", is_published=False
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 404

    async def test_method_mismatch_returns_405(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node(http_method="POST"))
        r = await api_client.get(f"/api/v1/webhook/{wf.id}")
        assert r.status_code == 405
        assert fake_workflow_service.calls == []

    async def test_header_auth_fail_returns_401(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        wf = await _make_workflow(
            db,
            node=_webhook_node(
                authentication={
                    "type": "header",
                    "header_name": "X-Api-Key",
                    "header_value": "abc",
                }
            ),
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 401
        assert fake_workflow_service.calls == []

    async def test_header_auth_pass(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        wf = await _make_workflow(
            db,
            node=_webhook_node(
                authentication={
                    "type": "header",
                    "header_name": "X-Api-Key",
                    "header_value": "abc",
                }
            ),
        )
        r = await api_client.post(
            f"/api/v1/webhook/{wf.id}", json={}, headers={"X-Api-Key": "abc"}
        )
        assert r.status_code == 200
        assert len(fake_workflow_service.calls) == 1

    async def test_respond_mode_immediately_does_not_wait(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node(respond_mode="immediately")
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 200
        assert fake_workflow_service.calls[0]["wait"] is False

    async def test_respond_mode_on_finish_returns_output(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        fake_workflow_service.on_finish_output = {
            "data": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        }
        wf = await _make_workflow(
            db,
            node=_webhook_node(
                respond_mode="on_finish", response_data="first_entry_json"
            ),
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 200
        assert r.json() == {"id": 1, "name": "alice"}
        assert fake_workflow_service.calls[0]["wait"] is True

    async def test_respond_mode_on_finish_all_entries(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        fake_workflow_service.on_finish_output = {
            "data": [{"id": 1}, {"id": 2}]
        }
        wf = await _make_workflow(
            db,
            node=_webhook_node(
                respond_mode="on_finish", response_data="all_entries"
            ),
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 200
        assert r.json() == [{"id": 1}, {"id": 2}]

    async def test_respond_mode_using_respond_node_returns_501(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node(respond_mode="using_respond_node")
        )
        r = await api_client.post(f"/api/v1/webhook/{wf.id}", json={})
        assert r.status_code == 501

    async def test_unknown_path_returns_404(self, api_client) -> None:
        r = await api_client.post("/api/v1/webhook/does-not-exist", json={})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# CORS preflight (OPTIONS) na rota de producao
# ---------------------------------------------------------------------------

async def _set_allowed_origins(
    db: AsyncSession, wf: Workflow, allowed_origins: str
) -> None:
    """Atualiza ``allowed_origins`` no primeiro no do workflow.

    Reatribui ``definition`` inteiro para o SQLAlchemy detectar a
    mutacao no JSONB (change-tracking nao propaga em dicts aninhados
    sem ``flag_modified``).
    """
    nodes = [dict(n) for n in wf.definition.get("nodes") or []]
    nodes[0]["data"] = {**nodes[0]["data"], "allowed_origins": allowed_origins}
    wf.definition = {**wf.definition, "nodes": nodes}
    await db.commit()


class TestCorsPreflight:
    async def test_options_preflight_with_wildcard_origin(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node(http_method="POST"))
        await _set_allowed_origins(db, wf, "*")

        r = await api_client.options(
            f"/api/v1/webhook/{wf.id}",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code == 204
        assert r.headers["access-control-allow-origin"] in (
            "https://app.example.com",
            "*",
        )
        assert "POST" in r.headers["access-control-allow-methods"]

    async def test_options_preflight_with_specific_origin_list(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node(http_method="POST"))
        await _set_allowed_origins(db, wf, "https://a.com, https://b.com")

        r = await api_client.options(
            f"/api/v1/webhook/{wf.id}",
            headers={
                "Origin": "https://a.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert r.status_code == 204
        assert r.headers["access-control-allow-origin"] == "https://a.com"

    async def test_options_preflight_origin_not_allowed(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node(http_method="POST"))
        await _set_allowed_origins(db, wf, "https://a.com")

        r = await api_client.options(
            f"/api/v1/webhook/{wf.id}",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert r.status_code == 204
        # Sem header de allow-origin — navegador bloqueia sozinho.
        assert "access-control-allow-origin" not in r.headers

    async def test_options_preflight_works_in_draft(
        self, api_client, db: AsyncSession
    ) -> None:
        """Preflight nao pode depender de o workflow estar publicado —
        senao o CORS quebra antes mesmo de o usuario subir pra producao."""
        wf = await _make_workflow(
            db,
            node=_webhook_node(http_method="POST"),
            status="draft",
            is_published=False,
        )
        await _set_allowed_origins(db, wf, "*")

        r = await api_client.options(
            f"/api/v1/webhook/{wf.id}",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert r.status_code == 204


# ---------------------------------------------------------------------------
# Testes da rota de teste /api/v1/webhook-test/{path}
# ---------------------------------------------------------------------------

class TestWebhookTestCapture:
    async def test_captures_payload_without_dispatching(
        self,
        api_client,
        db: AsyncSession,
        fake_workflow_service: _FakeWorkflowService,
    ) -> None:
        # Mesmo em draft/unpublished: a URL de teste funciona.
        wf = await _make_workflow(
            db,
            node=_webhook_node("n1", http_method="POST"),
            status="draft",
            is_published=False,
        )

        r = await api_client.post(
            f"/api/v1/webhook-test/{wf.id}",
            json={"event": "ping"},
            params={"src": "curl"},
        )
        assert r.status_code == 200
        assert fake_workflow_service.calls == []

        stored = await db.execute(
            select(WebhookTestCapture).where(
                WebhookTestCapture.workflow_id == wf.id,
                WebhookTestCapture.node_id == "n1",
            )
        )
        cap = stored.scalar_one()
        assert cap.method == "POST"
        assert cap.body == {"event": "ping"}
        assert cap.query_params.get("src") == "curl"

    async def test_upsert_overwrites_previous_capture(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node("n1", http_method="POST"))

        await api_client.post(f"/api/v1/webhook-test/{wf.id}", json={"n": 1})
        await api_client.post(f"/api/v1/webhook-test/{wf.id}", json={"n": 2})

        rows = (
            await db.execute(
                select(WebhookTestCapture).where(
                    WebhookTestCapture.workflow_id == wf.id
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].body == {"n": 2}


# ---------------------------------------------------------------------------
# Testes do endpoint de "Listen for test event"
# ---------------------------------------------------------------------------

class TestListenEndpoint:
    async def test_listen_returns_recent_pre_existing_by_default(
        self, api_client, db: AsyncSession
    ) -> None:
        """Default (fresh=False): uma captura ja existente e recente e
        retornada imediatamente — UX do n8n para quem faz curl antes de
        abrir a UI."""
        wf = await _make_workflow(db, node=_webhook_node("n1"))
        r0 = await api_client.post(
            f"/api/v1/webhook-test/{wf.id}", json={"old": True}
        )
        assert r0.status_code == 200

        r = await api_client.post(
            f"/api/v1/workflows/{wf.id}/webhook/listen",
            params={"node_id": "n1", "timeout_seconds": 5},
        )
        assert r.status_code == 200
        assert r.json()["body"] == {"old": True}

    async def test_listen_with_fresh_ignores_pre_existing_capture(
        self, api_client, db: AsyncSession
    ) -> None:
        """Com fresh=true a captura pre-existente e ignorada e o listen
        aguarda a proxima — util quando a UI quer forcar um novo evento."""
        wf = await _make_workflow(db, node=_webhook_node("n1"))
        r0 = await api_client.post(
            f"/api/v1/webhook-test/{wf.id}", json={"old": True}
        )
        assert r0.status_code == 200

        r = await api_client.post(
            f"/api/v1/workflows/{wf.id}/webhook/listen",
            params={
                "node_id": "n1",
                "timeout_seconds": 5,
                "fresh": "true",
            },
        )
        assert r.status_code == 408

    async def test_timeout_returns_408(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node("n1"))
        r = await api_client.post(
            f"/api/v1/workflows/{wf.id}/webhook/listen",
            params={"node_id": "n1", "timeout_seconds": 5},
        )
        assert r.status_code == 408

    async def test_capture_arrives_during_wait(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node("n1"))

        async def _post_later() -> None:
            await asyncio.sleep(0.3)
            await api_client.post(
                f"/api/v1/webhook-test/{wf.id}", json={"arrived": True}
            )

        poster = asyncio.create_task(_post_later())
        try:
            r = await api_client.post(
                f"/api/v1/workflows/{wf.id}/webhook/listen",
                params={"node_id": "n1", "timeout_seconds": 8},
            )
        finally:
            await poster

        assert r.status_code == 200
        assert r.json()["body"] == {"arrived": True}

    async def test_clear_removes_captures(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node("n1"))
        await api_client.post(f"/api/v1/webhook-test/{wf.id}", json={"x": 1})

        r = await api_client.delete(
            f"/api/v1/workflows/{wf.id}/webhook/listen",
            params={"node_id": "n1"},
        )
        assert r.status_code == 204

        rows = (
            await db.execute(
                select(WebhookTestCapture).where(
                    WebhookTestCapture.workflow_id == wf.id
                )
            )
        ).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# URLs endpoint
# ---------------------------------------------------------------------------

class TestWebhookUrls:
    async def test_default_path_is_workflow_id(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(db, node=_webhook_node("n1"))
        r = await api_client.get(f"/api/v1/workflows/{wf.id}/webhook/urls")
        assert r.status_code == 200
        body = r.json()
        assert body["node_id"] == "n1"
        assert body["path"] == str(wf.id)
        assert body["test_url"].endswith(f"/api/v1/webhook-test/{wf.id}")
        assert body["production_url"].endswith(f"/api/v1/webhook/{wf.id}")
        assert body["production_ready"] is True

    async def test_custom_path_used_when_set(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node("n1", path="orders/in")
        )
        r = await api_client.get(f"/api/v1/workflows/{wf.id}/webhook/urls")
        body = r.json()
        assert body["path"] == "orders/in"
        assert body["production_url"].endswith("/api/v1/webhook/orders/in")

    async def test_production_not_ready_when_draft(
        self, api_client, db: AsyncSession
    ) -> None:
        wf = await _make_workflow(
            db, node=_webhook_node("n1"), status="draft", is_published=False
        )
        r = await api_client.get(f"/api/v1/workflows/{wf.id}/webhook/urls")
        assert r.json()["production_ready"] is False
