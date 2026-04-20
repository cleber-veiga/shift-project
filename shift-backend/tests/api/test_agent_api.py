"""
Testes dos endpoints da API do Platform Agent.

Estrategia:
  - Mini-app FastAPI com as rotas do agent registradas.
  - Banco SQLite in-memory com compiladores de tipo Postgres.
  - get_current_user e get_db substituidos por fixtures.
  - authorization_service.has_permission mocado para retornar True.
  - agent_chat_service.stream_message e stream_resume mocados para
    emitir eventos SSE controlados sem tocar no grafo real.
  - get_checkpointer nao e chamado porque o grafo e mocado.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

# --- Compiladores SQLite para tipos Postgres ---

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@compiles(PGUUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "CHAR(36)"


# Importar DEPOIS de registrar compiladores
import sqlalchemy as sa  # noqa: E402

from app.api.dependencies import get_current_user, get_db  # noqa: E402
from app.api.v1.agent import router  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.security import authorization_service  # noqa: E402
from app.models.agent_thread import AgentThread  # noqa: E402
from app.models.agent_approval import AgentApproval  # noqa: E402
from app.models.agent_audit_log import AgentAuditLog  # noqa: E402
from app.models.agent_message import AgentMessage  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.events import sse_event, EVT_META, EVT_DONE, EVT_DELTA, EVT_APPROVAL_REQUIRED  # noqa: E402


# Metadata com apenas as tabelas necessarias para estes testes (evita DDL Postgres-only)
_TEST_TABLES = sa.MetaData()

_users_table = sa.Table(
    "users",
    _TEST_TABLES,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("email", sa.String(255), nullable=False),
    sa.Column("full_name", sa.String(255), nullable=True),
    sa.Column("hashed_password", sa.String(1024), nullable=True),
    sa.Column("is_active", sa.Boolean(), default=True),
    sa.Column("auth_provider", sa.String(50), nullable=False, server_default="local"),
    sa.Column("google_id", sa.String(255), nullable=True),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
)

_threads_table = sa.Table(
    "agent_threads",
    _TEST_TABLES,
    sa.Column("id", sa.String(36), primary_key=True, default=lambda: str(uuid.uuid4())),
    sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("workspace_id", sa.String(36), nullable=False),
    sa.Column("project_id", sa.String(36), nullable=True),
    sa.Column("title", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=False, default="running"),
    sa.Column("initial_context", sa.JSON(), nullable=False, default=dict),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
)

_approvals_table = sa.Table(
    "agent_approvals",
    _TEST_TABLES,
    sa.Column("id", sa.String(36), primary_key=True, default=lambda: str(uuid.uuid4())),
    sa.Column("thread_id", sa.String(36), sa.ForeignKey("agent_threads.id"), nullable=False),
    sa.Column("proposed_plan", sa.JSON(), nullable=False, default=dict),
    sa.Column("status", sa.Text(), nullable=False, default="pending"),
    sa.Column("decided_by", sa.String(36), nullable=True),
    sa.Column("decided_at", sa.DateTime(), nullable=True),
    sa.Column("rejection_reason", sa.Text(), nullable=True),
    sa.Column("expires_at", sa.DateTime(), nullable=False),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
)

_audit_table = sa.Table(
    "agent_audit_log",
    _TEST_TABLES,
    sa.Column("id", sa.String(36), primary_key=True, default=lambda: str(uuid.uuid4())),
    sa.Column("thread_id", sa.String(36), nullable=False),
    sa.Column("approval_id", sa.String(36), nullable=True),
    sa.Column("user_id", sa.String(36), nullable=False),
    sa.Column("tool_name", sa.Text(), nullable=False),
    sa.Column("tool_arguments", sa.JSON(), nullable=False, default=dict),
    sa.Column("tool_result_preview", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("error_message", sa.Text(), nullable=True),
    sa.Column("duration_ms", sa.Integer(), nullable=True),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
)

_messages_table = sa.Table(
    "agent_messages",
    _TEST_TABLES,
    sa.Column("id", sa.String(36), primary_key=True, default=lambda: str(uuid.uuid4())),
    sa.Column("thread_id", sa.String(36), sa.ForeignKey("agent_threads.id"), nullable=False),
    sa.Column("role", sa.Text(), nullable=False),
    sa.Column("content", sa.Text(), nullable=True),
    sa.Column("tool_calls", sa.JSON(), nullable=True),
    sa.Column("tool_call_id", sa.Text(), nullable=True),
    sa.Column("tool_name", sa.Text(), nullable=True),
    sa.Column("metadata", sa.JSON(), nullable=True),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
)


# ---------------------------------------------------------------------------
# Fixtures de banco e app
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(_TEST_TABLES.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def user(db: AsyncSession) -> User:
    u = User(
        id=uuid.uuid4(),
        email="agent@test.com",
        full_name="Agente Teste",
        hashed_password="x",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def thread(db: AsyncSession, user: User, workspace_id: uuid.UUID) -> AgentThread:
    t = AgentThread(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace_id,
        project_id=None,
        title="Teste",
        status="running",
        initial_context={"workspace_id": str(workspace_id)},
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest_asyncio.fixture
async def approval(db: AsyncSession, thread: AgentThread) -> AgentApproval:
    ap = AgentApproval(
        id=uuid.uuid4(),
        thread_id=thread.id,
        proposed_plan={"actions": [{"tool": "execute_workflow"}]},
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(ap)
    # Mark thread as awaiting
    thread.status = "awaiting_approval"
    await db.commit()
    await db.refresh(ap)
    return ap


def _make_sse_stream(*events: str) -> AsyncGenerator[str, None]:
    """Gera um async generator com eventos SSE pre-definidos."""
    async def _gen():
        for ev in events:
            yield ev
    return _gen()


@pytest_asyncio.fixture
async def api_client(session_factory, user, workspace_id):
    """Mini-app FastAPI com dependencias substituidas."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # state.limiter para slowapi
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    app.state.limiter = Limiter(key_func=get_remote_address)
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_get_user() -> User:
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_user

    # Sobrescrever require_permission para retornar None (bypass)
    async def _allow():
        return None

    for route in app.router.routes:
        if hasattr(route, "dependant"):
            for dep in route.dependant.dependencies:
                if dep.call is not None and getattr(
                    dep.call, "__qualname__", ""
                ).startswith("require_permission"):
                    app.dependency_overrides[dep.call] = _allow

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# 1. Flag AGENT_ENABLED desligada → 404
# ---------------------------------------------------------------------------


async def test_404_when_flag_disabled(api_client, workspace_id) -> None:
    with patch.object(settings, "AGENT_ENABLED", False):
        r = await api_client.get(f"/api/v1/agent/threads?workspace_id={workspace_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2. Flag ligada → 200 mesmo com lista vazia
# ---------------------------------------------------------------------------


async def test_list_threads_returns_empty_when_none(api_client, workspace_id) -> None:
    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.get(f"/api/v1/agent/threads?workspace_id={workspace_id}")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# 3. Criar thread sem mensagem inicial → 201 JSON
# ---------------------------------------------------------------------------


async def test_create_thread_without_message_returns_json(
    api_client, workspace_id
) -> None:
    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service, "has_permission", AsyncMock(return_value=True)
    ):
        r = await api_client.post(
            "/api/v1/agent/threads",
            json={
                "workspace_id": str(workspace_id),
                "screen_context": {"section": "workflows"},
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "id" in body
    assert body["status"] == "running"


# ---------------------------------------------------------------------------
# 4. Criar thread com mensagem inicial → SSE stream
# ---------------------------------------------------------------------------


async def test_create_thread_with_message_returns_sse(
    api_client, workspace_id
) -> None:
    stream_events = [
        sse_event("thread_created", {"thread_id": str(uuid.uuid4())}),
        sse_event(EVT_META, {"model": "test"}),
        sse_event(EVT_DELTA, {"text": "Resultado"}),
        sse_event(EVT_DONE, {"thread_status": "completed"}),
    ]

    async def _fake_stream(**_kw):
        async def _gen():
            for ev in stream_events:
                yield ev
        return _gen()

    with patch.object(settings, "AGENT_ENABLED", True), patch.object(
        authorization_service, "has_permission", AsyncMock(return_value=True)
    ), patch(
        "app.api.v1.agent.agent_chat_service.stream_message",
        side_effect=_fake_stream,
    ):
        r = await api_client.post(
            "/api/v1/agent/threads",
            json={
                "workspace_id": str(workspace_id),
                "initial_message": "liste meus workflows",
            },
        )

    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "Resultado" in r.text


# ---------------------------------------------------------------------------
# 5. Enviar mensagem → SSE stream
# ---------------------------------------------------------------------------


async def test_send_message_streams_events(
    api_client, thread: AgentThread
) -> None:
    stream_events = [
        sse_event(EVT_META, {"model": "test"}),
        sse_event(EVT_DELTA, {"text": "Resposta do agente"}),
        sse_event(EVT_DONE, {"thread_status": "completed"}),
    ]

    async def _fake_stream(**_kw):
        async def _gen():
            for ev in stream_events:
                yield ev
        return _gen()

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent.agent_chat_service.stream_message",
        side_effect=_fake_stream,
    ):
        r = await api_client.post(
            f"/api/v1/agent/threads/{thread.id}/messages",
            json={"message": "liste workflows"},
        )

    assert r.status_code == 200
    assert "Resposta do agente" in r.text


# ---------------------------------------------------------------------------
# 6. Thread em awaiting_approval nao aceita mensagem → 409
# ---------------------------------------------------------------------------


async def test_cannot_send_message_during_awaiting_approval(
    api_client, db: AsyncSession, thread: AgentThread
) -> None:
    thread.status = "awaiting_approval"
    await db.commit()

    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.post(
            f"/api/v1/agent/threads/{thread.id}/messages",
            json={"message": "oi"},
        )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 7. Approval: aprovacao bem-sucedida → SSE com execute e done
# ---------------------------------------------------------------------------


async def test_approve_resumes_and_executes(
    api_client, db: AsyncSession, thread: AgentThread, approval: AgentApproval
) -> None:
    stream_events = [
        sse_event(EVT_META, {"model": "test", "resuming": True}),
        sse_event(EVT_DELTA, {"text": "Workflow disparado com sucesso."}),
        sse_event(EVT_DONE, {"thread_status": "completed"}),
    ]

    async def _fake_resume(**_kw):
        async def _gen():
            for ev in stream_events:
                yield ev
        return _gen()

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent.agent_chat_service.stream_resume",
        side_effect=_fake_resume,
    ):
        r = await api_client.post(
            f"/api/v1/agent/threads/{thread.id}/approve",
            json={"approval_id": str(approval.id)},
        )

    assert r.status_code == 200
    assert "sucesso" in r.text


# ---------------------------------------------------------------------------
# 8. Reject encerra thread
# ---------------------------------------------------------------------------


async def test_reject_ends_thread_with_rejection_message(
    api_client, db: AsyncSession, thread: AgentThread, approval: AgentApproval
) -> None:
    stream_events = [
        sse_event(EVT_DELTA, {"text": "Operacao rejeitada: mudei de ideia."}),
        sse_event(EVT_DONE, {"thread_status": "completed"}),
    ]

    async def _fake_resume(**_kw):
        async def _gen():
            for ev in stream_events:
                yield ev
        return _gen()

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent.agent_chat_service.stream_resume",
        side_effect=_fake_resume,
    ):
        r = await api_client.post(
            f"/api/v1/agent/threads/{thread.id}/reject",
            json={"approval_id": str(approval.id), "reason": "mudei de ideia"},
        )

    assert r.status_code == 200
    assert "rejeitada" in r.text


# ---------------------------------------------------------------------------
# 9. Thread de outro usuario → 404 (nao 403 — evita enumeration)
# ---------------------------------------------------------------------------


async def test_cannot_access_other_users_thread(
    api_client, db: AsyncSession, workspace_id: uuid.UUID
) -> None:
    other_user_id = uuid.uuid4()
    other_thread = AgentThread(
        id=uuid.uuid4(),
        user_id=other_user_id,
        workspace_id=workspace_id,
        project_id=None,
        title="Outro user",
        status="running",
        initial_context={},
    )
    db.add(other_thread)
    await db.commit()

    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.get(f"/api/v1/agent/threads/{other_thread.id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 10. Aprovacao expirada → 410 Gone
# ---------------------------------------------------------------------------


async def test_cannot_approve_expired_approval(
    api_client, db: AsyncSession, thread: AgentThread
) -> None:
    expired = AgentApproval(
        id=uuid.uuid4(),
        thread_id=thread.id,
        proposed_plan={"actions": []},
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(expired)
    thread.status = "awaiting_approval"
    await db.commit()

    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.post(
            f"/api/v1/agent/threads/{thread.id}/approve",
            json={"approval_id": str(expired.id)},
        )
    assert r.status_code == 410


# ---------------------------------------------------------------------------
# 11. Delete com audit_log → 409
# ---------------------------------------------------------------------------


async def test_delete_with_audit_log_returns_409(
    api_client, db: AsyncSession, thread: AgentThread, user: User
) -> None:
    audit = AgentAuditLog(
        id=uuid.uuid4(),
        thread_id=thread.id,
        user_id=user.id,
        tool_name="list_workflows",
        tool_arguments={},
        status="success",
    )
    db.add(audit)
    await db.commit()

    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.delete(f"/api/v1/agent/threads/{thread.id}")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 12. Delete sem audit_log → 204
# ---------------------------------------------------------------------------


async def test_delete_without_audit_log_returns_204(
    api_client, db: AsyncSession, thread: AgentThread
) -> None:
    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.delete(f"/api/v1/agent/threads/{thread.id}")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# 13. Formato dos eventos SSE
# ---------------------------------------------------------------------------


async def test_sse_events_format(api_client, thread: AgentThread) -> None:
    """Valida que o stream usa 'event:' e 'data:' corretos."""
    stream_events = [
        sse_event(EVT_META, {"model": "test"}),
        sse_event(EVT_DONE, {"thread_status": "completed"}),
    ]

    async def _fake_stream(**_kw):
        async def _gen():
            for ev in stream_events:
                yield ev
        return _gen()

    with patch.object(settings, "AGENT_ENABLED", True), patch(
        "app.api.v1.agent.agent_chat_service.stream_message",
        side_effect=_fake_stream,
    ):
        r = await api_client.post(
            f"/api/v1/agent/threads/{thread.id}/messages",
            json={"message": "teste"},
        )

    assert r.status_code == 200
    body = r.text
    assert "event: meta" in body
    assert "event: done" in body
    assert "data: " in body


# ---------------------------------------------------------------------------
# 14. Listar threads do usuario
# ---------------------------------------------------------------------------


async def test_list_threads_returns_own_threads(
    api_client, thread: AgentThread, workspace_id: uuid.UUID
) -> None:
    with patch.object(settings, "AGENT_ENABLED", True):
        r = await api_client.get(
            f"/api/v1/agent/threads?workspace_id={workspace_id}"
        )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert str(thread.id) in ids
