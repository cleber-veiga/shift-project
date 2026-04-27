"""Testes do hardening de seguranca do dispatcher (Tarefa 2 6.2/6.3).

Cobre:
- ``follow_redirects=False`` configurado.
- 3xx -> outcome ``terminal`` (dead-letter sem retry).
- DNS rebinding em tempo de dispatch -> ``terminal``.
- Hostname publico que resolve pra IP publico passa.
- Metrica ``webhook_security_blocked_total`` incrementa nos casos certos.
- Logs nao vazam IP interno (so hostname).
"""

from __future__ import annotations

import socket
from uuid import uuid4

import httpx
import pytest


# Importa apos quaisquer fixtures de env — _resolve_and_check le envvar.
from app.services.webhook_dispatch_service import (
    WEBHOOK_SECURITY_BLOCKED,
    WebhookDispatchService,
    WebhookSecurityError,
    _resolve_and_check,
    _safe_host_from_redirect,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubSubscription:
    def __init__(self, url: str, secret: str = "s3cr3t"):
        self.id = uuid4()
        self.workspace_id = uuid4()
        self.url = url
        self.secret = secret


class _StubDelivery:
    def __init__(self, payload, event="execution.completed"):
        self.id = uuid4()
        self.event = event
        self.payload = payload


def _client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )


def _counter_value(metric, labels: tuple[str, ...]) -> float:
    """Le valor escalar de um Counter para a tupla de labels."""
    for sample in metric.collect():
        for s in sample.samples:
            if s.name.endswith("_total") and tuple(
                s.labels.get(k) for k in metric._labelnames
            ) == labels:
                return s.value
    return 0.0


# ---------------------------------------------------------------------------
# _resolve_and_check (Tarefa 2 — DNS rebinding)
# ---------------------------------------------------------------------------


class TestResolveAndCheck:
    def test_blocks_private_ip_resolution(self, monkeypatch):
        """Hostname publico que resolve pra 10.0.0.5 e bloqueado."""
        monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)

        def fake(host, port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]
        monkeypatch.setattr(socket, "getaddrinfo", fake)

        with pytest.raises(WebhookSecurityError):
            _resolve_and_check("evil.example", 443)

    def test_blocks_aws_metadata_resolution(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)

        def fake(host, port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]
        monkeypatch.setattr(socket, "getaddrinfo", fake)

        with pytest.raises(WebhookSecurityError):
            _resolve_and_check("evil.example", 443)

    def test_allows_public_ip_resolution(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)

        def fake(host, port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
        monkeypatch.setattr(socket, "getaddrinfo", fake)

        # Nao levanta.
        _resolve_and_check("dns.google", 443)

    def test_dns_unresolvable_raises_security_error(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)

        def fake(*args, **kwargs):
            raise socket.gaierror("not found")
        monkeypatch.setattr(socket, "getaddrinfo", fake)

        with pytest.raises(WebhookSecurityError):
            _resolve_and_check("nope.example", 443)

    def test_bypass_skips_resolution(self, monkeypatch):
        """Com flag ligada, ``_resolve_and_check`` retorna sem chamar DNS."""
        monkeypatch.setenv("WEBHOOK_ALLOW_INSECURE_HOSTS", "true")

        def must_not_be_called(*args, **kwargs):
            raise AssertionError("getaddrinfo nao deveria rodar")
        monkeypatch.setattr(socket, "getaddrinfo", must_not_be_called)

        _resolve_and_check("anything", 443)


# ---------------------------------------------------------------------------
# _post_one — caminho integrado com o dispatcher
# ---------------------------------------------------------------------------


@pytest.fixture
def public_dns(monkeypatch):
    """Faz qualquer host resolver pra 8.8.8.8 (publico)."""
    monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)

    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture
def rebinding_to_internal(monkeypatch):
    """Faz qualquer host resolver pra 10.0.0.5 — simula DNS rebind."""
    monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)

    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


class TestRedirectBlocking:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    async def test_redirect_to_internal_is_terminal(self, status, public_dns):
        """Cliente externo que devolve 3xx para 127.0.0.1 vai pra dead-letter."""
        before = _counter_value(WEBHOOK_SECURITY_BLOCKED, ("redirect_blocked",))

        async def handler(request):
            return httpx.Response(
                status,
                headers={"Location": "http://127.0.0.1/admin"},
            )

        svc = WebhookDispatchService()
        async with _client(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"x": 1}),
                _StubSubscription("https://external.example/hook"),
            )

        assert outcome.kind == "terminal"
        assert outcome.status_code == status
        assert "redirect" in (outcome.error or "").lower()

        after = _counter_value(WEBHOOK_SECURITY_BLOCKED, ("redirect_blocked",))
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_log_redirect_does_not_leak_path(self, public_dns, caplog):
        """Mensagem em log mostra hosts, nao paths sensitivos."""
        async def handler(_request):
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/admin/secrets/dump"},
            )

        svc = WebhookDispatchService()
        with caplog.at_level("WARNING", logger="app.services.webhook_dispatch_service"):
            async with _client(handler) as client:
                await svc._post_one(
                    client,
                    _StubDelivery({"x": 1}),
                    _StubSubscription("https://external.example/hook"),
                )
        # Nao loga o path sensitivo.
        joined = " ".join(r.message for r in caplog.records)
        assert "/admin/secrets" not in joined


class TestDnsRebindAtDispatch:
    @pytest.mark.asyncio
    async def test_dns_rebind_to_internal_is_terminal(self, rebinding_to_internal):
        """Hostname externo cuja resolucao foi rebindada para IP interno
        e bloqueado ANTES do POST."""
        before = _counter_value(WEBHOOK_SECURITY_BLOCKED, ("ssrf_dns_rebind",))

        async def handler(_request):
            # Nao deveria nunca rodar — bloqueio acontece antes do post.
            raise AssertionError("Request foi enviado, mas deveria ter bloqueado.")

        svc = WebhookDispatchService()
        async with _client(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"x": 1}),
                _StubSubscription("https://external.example/hook"),
            )

        assert outcome.kind == "terminal"
        assert outcome.status_code is None
        assert "seguranca" in (outcome.error or "").lower()

        after = _counter_value(WEBHOOK_SECURITY_BLOCKED, ("ssrf_dns_rebind",))
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_log_dns_rebind_does_not_leak_resolved_ip(
        self, rebinding_to_internal, caplog,
    ):
        """Log mostra so hostname, nao o IP resolvido."""
        async def handler(_request):
            raise AssertionError("nao deveria postar")

        svc = WebhookDispatchService()
        with caplog.at_level("WARNING", logger="app.services.webhook_dispatch_service"):
            async with _client(handler) as client:
                await svc._post_one(
                    client,
                    _StubDelivery({"x": 1}),
                    _StubSubscription("https://external.example/hook"),
                )
        joined = " ".join(r.message + " " + str(r.args or "") for r in caplog.records)
        assert "10.0.0.5" not in joined


class TestExternalLegitimatePass:
    @pytest.mark.asyncio
    async def test_external_legitimate_passes(self, public_dns):
        """Hostname publico, resolve pra IP publico, responde 200 → success."""
        async def handler(_request):
            return httpx.Response(200, json={"ack": True})

        svc = WebhookDispatchService()
        async with _client(handler) as client:
            outcome = await svc._post_one(
                client,
                _StubDelivery({"x": 1}),
                _StubSubscription("https://hooks.slack.com/services/T/B/X"),
            )
        assert outcome.kind == "success"
        assert outcome.status_code == 200


class TestSafeHostHelper:
    @pytest.mark.parametrize(
        "loc,expected",
        [
            ("http://127.0.0.1/admin", "127.0.0.1"),
            ("https://example.com:8443/x?token=abc", "example.com"),
            ("/relative/path", "<relative>"),
            ("", "<empty>"),
            ("not a url", "<relative>"),  # urlparse aceita silenciosamente
        ],
    )
    def test_extracts_only_host(self, loc, expected):
        assert _safe_host_from_redirect(loc) == expected
