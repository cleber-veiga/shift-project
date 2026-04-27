"""Integration tests do dispatch de webhooks (Prompt 6.3).

Cobrem o ciclo completo com Postgres real:
- enqueue_for_event cria deliveries para subscriptions ativas.
- dispatch_due picka, faz POST mockado, e atualiza estado.
- 5xx -> retry com backoff (next_attempt_at no futuro).
- timeout -> retry.
- 4xx -> dead-letter imediato (sem retry).
- max_attempts esgotado -> dead-letter.
- Replay de dead-letter cria nova delivery.

Marker
------
``@pytest.mark.postgres``: precisa de Postgres com as migrations aplicadas.
``DATABASE_URL`` deve apontar para um Postgres acessivel; CI roda com
``alembic upgrade head`` antes da suite.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text


# ---------------------------------------------------------------------------
# Postgres skip helper (replica a logica de test_snapshot_immutability_trigger)
# ---------------------------------------------------------------------------


def _check_postgres() -> tuple[bool, str]:
    try:
        from app.core.config import settings
        if "postgres" not in settings.DATABASE_URL.lower():
            return False, "DATABASE_URL nao aponta para Postgres"
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _check() -> tuple[bool, str]:
            engine = create_async_engine(settings.DATABASE_URL)
            try:
                async with engine.connect() as conn:
                    has_table = (
                        await conn.execute(
                            text(
                                "SELECT 1 FROM information_schema.tables "
                                "WHERE table_name = 'webhook_subscriptions'"
                            )
                        )
                    ).scalar()
                    if not has_table:
                        return False, (
                            "tabela webhook_subscriptions ausente — rode "
                            "``alembic upgrade head`` antes desta suite"
                        )
                    return True, ""
            finally:
                await engine.dispose()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_check())
        finally:
            loop.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"erro conectando ao Postgres: {exc}"


_PG_OK, _PG_SKIP_REASON = _check_postgres()
_REQUIRES_POSTGRES = pytest.mark.skipif(
    not _PG_OK, reason=f"Postgres + migrations indisponiveis: {_PG_SKIP_REASON}"
)


@pytest.fixture(autouse=True)
def _allow_test_hosts(monkeypatch):
    """As subscriptions semeadas usam ``client.example.com`` — sem o
    bypass, o ``_resolve_and_check`` (Tarefa 2 do hardening) tentaria
    resolver via DNS real e bloquearia. Como esses testes querem isolar
    a fila/dispatch, ligamos o flag dev-only."""
    monkeypatch.setenv("WEBHOOK_ALLOW_INSECURE_HOSTS", "true")


@pytest.fixture(autouse=True)
async def _clean_pending_deliveries():
    """Cleanup entre testes: descarta deliveries pendentes antigas E o
    engine SQLAlchemy global.

    Razoes:
    1. ``dispatch_due`` e global — sem cleanup, leaks de testes anteriores
       seriam pickados e contaminariam asserts.
    2. ``app.db.session.engine`` e modulo-level. pytest-asyncio em
       ``mode=auto`` cria um event loop por teste; asyncpg fica preso
       no primeiro loop. Damos ``await engine.dispose()`` no final pra
       forcar uma reconstrucao limpa no proximo teste — caro (cold
       reconnect), mas o suite e pequeno e a alternativa e configurar
       loop scope global, que afeta os outros testes.
    """
    if not _PG_OK:
        yield
        return
    from app.db.session import async_session_factory, engine
    from sqlalchemy import update as sa_update
    from app.models.webhook_subscription import WebhookDelivery
    async with async_session_factory() as session:
        await session.execute(
            sa_update(WebhookDelivery)
            .where(WebhookDelivery.status.in_(["pending", "in_flight"]))
            .values(status="failed", failed_at=datetime.now(timezone.utc))
        )
        await session.commit()
    yield
    # Teardown — descarta o pool atual.
    try:
        await engine.dispose()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_workspace_and_subscription(
    session, *, url: str = "https://client.example.com/hook",
    events: list[str] | None = None,
):
    """Cria organization -> workspace -> webhook_subscription minimo.

    Retorna ``(workspace_id, subscription_id)``. Usa a ORM para poder ler
    a subscription depois sem precisar reconstruir o objeto a mao.
    """
    from app.models import WebhookSubscription, Workspace
    from app.models.organization import Organization

    org = Organization(id=uuid.uuid4(), name=f"org-{uuid.uuid4().hex[:6]}")
    session.add(org)
    await session.flush()

    ws = Workspace(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=f"ws-{uuid.uuid4().hex[:6]}",
    )
    session.add(ws)
    await session.flush()

    sub = WebhookSubscription(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        url=url,
        events=events or ["execution.completed", "execution.failed"],
        secret="test-secret-1234567890abcdef",
        active=True,
    )
    session.add(sub)
    await session.commit()
    return ws.id, sub.id


def _mock_transport(handler):
    """Atalho — httpx.MockTransport recebe um handler async."""
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.postgres
@_REQUIRES_POSTGRES
class TestEnqueueAndDispatchSuccess:
    @pytest.mark.asyncio
    async def test_enqueue_creates_one_delivery_per_active_subscription(self):
        from app.db.session import async_session_factory
        from app.models import WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            count = await webhook_dispatch_service.enqueue_for_event(
                session,
                workspace_id=ws_id,
                event="execution.completed",
                payload={"execution_id": str(uuid.uuid4()), "status": "completed"},
            )
            await session.commit()
            assert count == 1

            result = await session.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.subscription_id == sub_id
                )
            )
            deliveries = list(result.scalars().all())
            assert len(deliveries) == 1
            d = deliveries[0]
            assert d.status == "pending"
            assert d.attempt_count == 0
            assert d.event == "execution.completed"

    @pytest.mark.asyncio
    async def test_dispatch_due_marks_delivered_on_2xx(self):
        from app.db.session import async_session_factory
        from app.models import WebhookDelivery, WebhookSubscription
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async def handler(_request):
            return httpx.Response(200, json={"ack": True})

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"execution_id": str(uuid.uuid4())},
            )
            await session.commit()

        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        async with async_session_factory() as session:
            result = await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )
            d = result.scalar_one()
            assert d.status == "delivered"
            assert d.attempt_count == 1
            assert d.last_status_code == 200
            assert d.delivered_at is not None
            sub = await session.get(WebhookSubscription, sub_id)
            assert sub.last_status_code == 200


@pytest.mark.postgres
@_REQUIRES_POSTGRES
class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_5xx_schedules_retry_with_backoff(self):
        from app.db.session import async_session_factory
        from app.models import WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async def handler(_request):
            return httpx.Response(503)

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"x": 1},
            )
            await session.commit()

        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        async with async_session_factory() as session:
            result = await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )
            d = result.scalar_one()
            assert d.status == "pending"
            assert d.attempt_count == 1
            assert d.last_status_code == 503
            # ``next_attempt_at`` foi recalculado via ``compute_next_attempt_delay(1)``
            # (= 1s). Nao testamos o offset absoluto — bancos remotos (Neon
            # serverless) podem injetar segundos de latencia entre o
            # ``before`` do teste e o ``persist_outcome`` do servico. O que
            # importa: a proxima tentativa NAO e imediata (esta no futuro).
            assert d.next_attempt_at > d.created_at

    @pytest.mark.asyncio
    async def test_timeout_schedules_retry(self):
        from app.db.session import async_session_factory
        from app.models import WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async def handler(_request):
            raise httpx.ReadTimeout("client took >10s")

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"x": 1},
            )
            await session.commit()

        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        async with async_session_factory() as session:
            result = await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )
            d = result.scalar_one()
            assert d.status == "pending"
            assert d.attempt_count == 1
            assert d.last_status_code is None
            assert "timeout" in (d.last_error or "").lower()

    @pytest.mark.asyncio
    async def test_4xx_goes_straight_to_dead_letter(self):
        from app.db.session import async_session_factory
        from app.models import WebhookDeadLetter, WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async def handler(_request):
            return httpx.Response(400, text="bad request")

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"x": 1},
            )
            await session.commit()

        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        async with async_session_factory() as session:
            d = (await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )).scalar_one()
            # 4xx = terminal, sem retry.
            assert d.status == "failed"
            assert d.attempt_count == 1
            assert d.last_status_code == 400
            assert d.failed_at is not None

            dl = (await session.execute(
                select(WebhookDeadLetter).where(
                    WebhookDeadLetter.subscription_id == sub_id
                )
            )).scalar_one()
            assert dl.last_status_code == 400
            assert dl.payload == {"x": 1}
            assert dl.delivery_id == d.id

    @pytest.mark.asyncio
    async def test_dead_letter_after_max_attempts_5xx(self):
        """Apos esgotar max_attempts em 5xx, vai para dead-letter."""
        from app.db.session import async_session_factory
        from app.models import WebhookDeadLetter, WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async def handler(_request):
            return httpx.Response(503)

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"x": 1},
            )
            await session.commit()
            # Override max_attempts pra 2 e zera next_attempt_at, aceleraremos
            # avancando o relogio entre dispatches.
            d = (await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )).scalar_one()
            d.max_attempts = 2
            await session.commit()

        # 1a tentativa — falha 5xx, agenda retry.
        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        # Adianta next_attempt_at pra ja e roda denovo.
        async with async_session_factory() as session:
            d = (await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )).scalar_one()
            d.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        # 2a tentativa — falha 5xx novamente, ja esgotou: dead-letter.
        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        async with async_session_factory() as session:
            d = (await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
            )).scalar_one()
            assert d.status == "failed"
            assert d.attempt_count == 2

            dl = (await session.execute(
                select(WebhookDeadLetter).where(
                    WebhookDeadLetter.subscription_id == sub_id
                )
            )).scalar_one()
            assert dl.attempt_count == 2
            assert dl.last_status_code == 503


@pytest.mark.postgres
@_REQUIRES_POSTGRES
class TestEventFiltering:
    @pytest.mark.asyncio
    async def test_subscription_only_gets_subscribed_events(self):
        """Subscription que so assina ``execution.failed`` nao deve receber
        ``execution.completed``."""
        from app.db.session import async_session_factory
        from app.models import WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(
                session, events=["execution.failed"],
            )
            count = await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"x": 1},
            )
            await session.commit()
            assert count == 0

            # Ja para ``execution.failed`` — bate.
            count = await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.failed",
                payload={"x": 1},
            )
            await session.commit()
            assert count == 1

    @pytest.mark.asyncio
    async def test_inactive_subscription_skipped(self):
        from app.db.session import async_session_factory
        from app.models import WebhookSubscription
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            sub = await session.get(WebhookSubscription, sub_id)
            sub.active = False
            await session.commit()

            count = await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"x": 1},
            )
            await session.commit()
            assert count == 0


@pytest.mark.postgres
@_REQUIRES_POSTGRES
class TestReplay:
    @pytest.mark.asyncio
    async def test_replay_dead_letter_creates_new_delivery(self):
        from app.db.session import async_session_factory
        from app.models import WebhookDeadLetter, WebhookDelivery
        from app.services.webhook_dispatch_service import (
            webhook_dispatch_service,
        )

        # Provoca dead-letter via 4xx.
        async def fail_handler(_request):
            return httpx.Response(403)

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"replay_test": "yes"},
            )
            await session.commit()

        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(fail_handler))

        async with async_session_factory() as session:
            dl = (await session.execute(
                select(WebhookDeadLetter).where(
                    WebhookDeadLetter.subscription_id == sub_id
                )
            )).scalar_one()
            new_delivery = await webhook_dispatch_service.replay_dead_letter(
                session, dead_letter=dl,
            )
            await session.commit()
            assert new_delivery.subscription_id == sub_id
            assert new_delivery.event == "execution.completed"
            assert new_delivery.payload == {"replay_test": "yes"}
            assert new_delivery.status == "pending"
            assert dl.resolved_at is not None


@pytest.mark.postgres
@_REQUIRES_POSTGRES
class TestSignatureOnTheWire:
    @pytest.mark.asyncio
    async def test_x_shift_signature_validates_with_subscription_secret(self):
        """A assinatura que chega no cliente deve bater HMAC(secret, body)."""
        from app.db.session import async_session_factory
        from app.services.webhook_dispatch_service import (
            verify_signature,
            webhook_dispatch_service,
        )

        captured = {}

        async def handler(request: httpx.Request):
            captured["headers"] = dict(request.headers)
            captured["body"] = bytes(request.content)
            return httpx.Response(200)

        async with async_session_factory() as session:
            ws_id, sub_id = await _seed_workspace_and_subscription(session)
            await webhook_dispatch_service.enqueue_for_event(
                session, workspace_id=ws_id, event="execution.completed",
                payload={"a": 1, "b": 2},
            )
            await session.commit()

        await webhook_dispatch_service.dispatch_due(transport=_mock_transport(handler))

        secret = "test-secret-1234567890abcdef"  # mesmo do _seed_workspace
        assert verify_signature(
            secret, captured["body"], captured["headers"]["x-shift-signature"]
        )
        # Confere que o signature **NAO** valida com secret errado — guarda
        # contra teste tautologico.
        assert not verify_signature(
            "wrong-secret", captured["body"],
            captured["headers"]["x-shift-signature"],
        )
