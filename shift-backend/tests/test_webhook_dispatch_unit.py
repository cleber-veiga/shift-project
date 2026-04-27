"""Unit tests para a logica de dispatch de webhooks (Prompt 6.3).

Testes que NAO precisam de DB — focam em:
- HMAC: assinatura valida com secret correto, invalida com secret errado.
- Backoff: sequencia 1s, 5s, 30s, 5min, 30min, 2h.
- Classificacao do outcome (200 -> success, 5xx -> retry, 4xx -> terminal,
  timeout -> retry).
- Serializacao deterministica do payload (mesmo input -> mesma assinatura).

Os testes que envolvem DB (enqueue, dispatch_due, dead-letter) ficam em
``test_webhook_dispatch_integration.py`` e dependem de Postgres.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest


@pytest.fixture(autouse=True)
def _bypass_ssrf_checks(monkeypatch):
    """Os stubs usam ``client.example.com`` etc. Ligar o bypass dev-only
    evita DNS lookup real e mantem o foco do teste em classificacao do
    outcome (dominio destes testes). Os testes de SSRF dedicados ficam em
    ``tests/services/webhooks/`` e ``test_webhook_dispatcher_security.py``.
    """
    monkeypatch.setenv("WEBHOOK_ALLOW_INSECURE_HOSTS", "true")


from app.services.webhook_dispatch_service import (
    DEFAULT_HTTP_TIMEOUT_S,
    DEFAULT_MAX_ATTEMPTS,
    WebhookDispatchService,
    _BACKOFF_SECONDS,
    _DeliveryOutcome,
    _serialize_payload,
    compute_next_attempt_delay,
    compute_signature,
    generate_secret,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Stubs sem DB
# ---------------------------------------------------------------------------


class _StubSubscription:
    """Subscription minima para os testes de _post_one sem ORM."""

    def __init__(self, url: str, secret: str = "s3cr3t"):
        from uuid import uuid4
        self.id = uuid4()
        self.workspace_id = uuid4()
        self.url = url
        self.secret = secret


class _StubDelivery:
    """Delivery minima para os testes de _post_one sem ORM."""

    def __init__(self, payload: dict[str, Any], event: str = "execution.completed"):
        from uuid import uuid4
        self.id = uuid4()
        self.event = event
        self.payload = payload


# ---------------------------------------------------------------------------
# HMAC
# ---------------------------------------------------------------------------


class TestSignature:
    def test_signature_round_trip(self):
        body = b'{"event":"x"}'
        sig = compute_signature("mysecret", body)
        assert sig.startswith("sha256=")
        assert verify_signature("mysecret", body, sig)

    def test_signature_invalid_with_wrong_secret(self):
        body = b'{"event":"x"}'
        sig = compute_signature("mysecret", body)
        assert not verify_signature("wrongsecret", body, sig)

    def test_signature_invalid_with_tampered_body(self):
        sig = compute_signature("mysecret", b'{"a":1}')
        assert not verify_signature("mysecret", b'{"a":2}', sig)

    def test_signature_rejects_missing_prefix(self):
        # Sem ``sha256=`` na frente, rejeita mesmo que o hex coincida.
        body = b'{"event":"x"}'
        sig_full = compute_signature("mysecret", body)
        sig_no_prefix = sig_full.replace("sha256=", "")
        assert not verify_signature("mysecret", body, sig_no_prefix)

    def test_generate_secret_is_unique_and_long_enough(self):
        secrets_set = {generate_secret() for _ in range(10)}
        assert len(secrets_set) == 10
        for s in secrets_set:
            # token_urlsafe(32) -> ~43 chars
            assert len(s) >= 40


# ---------------------------------------------------------------------------
# Serializacao deterministica
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_sorted_keys_for_determinism(self):
        a = _serialize_payload({"b": 2, "a": 1})
        b = _serialize_payload({"a": 1, "b": 2})
        assert a == b
        assert json.loads(a) == {"a": 1, "b": 2}

    def test_serializes_uuid_via_default_str(self):
        from uuid import uuid4
        u = uuid4()
        out = _serialize_payload({"execution_id": u})
        assert json.loads(out) == {"execution_id": str(u)}


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_official_sequence(self):
        # Spec: 1s, 5s, 30s, 5min, 30min, 2h
        assert _BACKOFF_SECONDS == (1, 5, 30, 300, 1800, 7200)

    @pytest.mark.parametrize(
        "attempt, expected",
        [(1, 1), (2, 5), (3, 30), (4, 300), (5, 1800), (6, 7200)],
    )
    def test_backoff_returns_expected_seconds(self, attempt, expected):
        assert compute_next_attempt_delay(attempt) == expected

    def test_zero_attempt_returns_zero(self):
        assert compute_next_attempt_delay(0) == 0

    def test_overflow_attempt_clamps_to_last(self):
        # max_attempts > len(_BACKOFF_SECONDS) deve continuar com o ultimo valor.
        assert compute_next_attempt_delay(10) == 7200

    def test_default_max_attempts_is_six(self):
        # Spec: max 6 tentativas.
        assert DEFAULT_MAX_ATTEMPTS == 6


# ---------------------------------------------------------------------------
# Classificacao do outcome em _post_one
# ---------------------------------------------------------------------------


def _client_with_handler(handler) -> httpx.AsyncClient:
    """Cria AsyncClient com MockTransport que executa o ``handler``."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestPostOneClassification:
    """_post_one deve mapear status code/error em ``_DeliveryOutcome.kind``.

    - 2xx        -> success
    - 4xx        -> terminal (sem retry)
    - 5xx        -> retryable
    - timeout    -> retryable
    - network    -> retryable
    """

    @pytest.mark.asyncio
    async def test_2xx_is_success(self):
        async def handler(_request):
            return httpx.Response(200, json={"ok": True})

        svc = WebhookDispatchService()
        sub = _StubSubscription("https://client.example.com/hook")
        delivery = _StubDelivery({"event": "x"})
        async with _client_with_handler(handler) as client:
            outcome = await svc._post_one(client, delivery, sub)
        assert outcome.kind == "success"
        assert outcome.status_code == 200

    @pytest.mark.asyncio
    async def test_201_is_success(self):
        async def handler(_request):
            return httpx.Response(201)

        svc = WebhookDispatchService()
        async with _client_with_handler(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"event": "x"}),
                _StubSubscription("https://client.example.com/hook"),
            )
        assert outcome.kind == "success"
        assert outcome.status_code == 201

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    async def test_4xx_is_terminal(self, code):
        async def handler(_request):
            return httpx.Response(code, text="bad request")

        svc = WebhookDispatchService()
        async with _client_with_handler(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"event": "x"}),
                _StubSubscription("https://client.example.com/hook"),
            )
        assert outcome.kind == "terminal"
        assert outcome.status_code == code

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", [500, 502, 503, 504])
    async def test_5xx_is_retryable(self, code):
        async def handler(_request):
            return httpx.Response(code)

        svc = WebhookDispatchService()
        async with _client_with_handler(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"event": "x"}),
                _StubSubscription("https://client.example.com/hook"),
            )
        assert outcome.kind == "retryable"
        assert outcome.status_code == code

    @pytest.mark.asyncio
    async def test_timeout_is_retryable(self):
        async def handler(_request):
            raise httpx.ReadTimeout("simulated 10s timeout")

        svc = WebhookDispatchService()
        async with _client_with_handler(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"event": "x"}),
                _StubSubscription("https://client.example.com/hook"),
            )
        assert outcome.kind == "retryable"
        assert outcome.status_code is None
        assert "timeout" in outcome.error.lower()

    @pytest.mark.asyncio
    async def test_connect_error_is_retryable(self):
        async def handler(_request):
            raise httpx.ConnectError("DNS refused")

        svc = WebhookDispatchService()
        async with _client_with_handler(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"event": "x"}),
                _StubSubscription("https://client.example.com/hook"),
            )
        assert outcome.kind == "retryable"

    @pytest.mark.asyncio
    async def test_signature_header_is_set(self):
        captured: dict[str, str] = {}

        async def handler(request: httpx.Request):
            captured.update(dict(request.headers))
            return httpx.Response(200)

        svc = WebhookDispatchService()
        sub = _StubSubscription("https://client.example.com/hook", secret="abc")
        delivery = _StubDelivery({"hello": "world"})
        async with _client_with_handler(handler) as client:
            await svc._post_one(client, delivery, sub)

        # Headers existem e a assinatura bate o body real.
        assert captured.get("x-shift-event") == "execution.completed"
        assert captured.get("x-shift-delivery-id") == str(delivery.id)
        assert "x-shift-timestamp" in captured
        sig = captured.get("x-shift-signature", "")
        assert sig.startswith("sha256=")
        # Recalcula HMAC e confirma — body deterministico (sort_keys=True).
        expected_body = _serialize_payload({"hello": "world"})
        expected_sig = compute_signature("abc", expected_body)
        assert sig == expected_sig
