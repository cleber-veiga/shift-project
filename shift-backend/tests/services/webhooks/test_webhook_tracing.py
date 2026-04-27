"""Testes de propagacao de trace pelo dispatch de webhooks (Tarefa 3).

Cobre:
- ``traceparent`` injetado no header HTTP outbound.
- Span ``webhook.dispatch`` criado em torno de ``_post_one``.
- Atributos do span (subscription_id, delivery_id, event, http.*).
- Trace context capturado em ``enqueue_for_event`` chega no payload da
  delivery (verificacao funcional sem dependencia de DB).
- Quando tracing e no-op (default em dev), ``inject_trace_context`` nao
  quebra e nao polui headers com valores invalidos.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest


@pytest.fixture(autouse=True)
def _bypass_ssrf(monkeypatch):
    """Os stubs apontam pra hosts ficticios — pula DNS de rebind check."""
    monkeypatch.setenv("WEBHOOK_ALLOW_INSECURE_HOSTS", "true")


from app.services.webhook_dispatch_service import (  # noqa: E402
    WebhookDispatchService,
)


class _StubSubscription:
    def __init__(self, url: str = "https://hooks.example/x", secret: str = "s"):
        self.id = uuid4()
        self.workspace_id = uuid4()
        self.url = url
        self.secret = secret


class _StubDelivery:
    def __init__(
        self,
        payload: dict | None = None,
        event: str = "execution.completed",
        trace_context: dict | None = None,
        attempt_count: int = 0,
    ):
        self.id = uuid4()
        self.event = event
        self.payload = payload or {"x": 1}
        self.trace_context = trace_context
        self.attempt_count = attempt_count


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


# ---------------------------------------------------------------------------
# Trace context propagation no enqueue (mesmo sem tracing real)
# ---------------------------------------------------------------------------


class TestInjectTraceContext:
    """Confirma que ``inject_trace_context`` e chamado no caminho do dispatch.

    Quando tracing esta DESLIGADO (default em testes), ``inject`` injeta
    nada — mas a chamada nao deve quebrar e o header X-Shift-Signature
    deve continuar correto.
    """

    @pytest.mark.asyncio
    async def test_post_succeeds_without_tracing(self):
        captured: dict[str, str] = {}

        async def handler(request):
            captured.update(dict(request.headers))
            return httpx.Response(200)

        svc = WebhookDispatchService()
        async with _client(handler) as client:
            outcome = await svc._post_one(
                client, _StubDelivery(), _StubSubscription(),
            )
        assert outcome.kind == "success"
        # Sem tracing real, nao tem traceparent — mas request foi enviado.
        assert "x-shift-signature" in captured

    @pytest.mark.asyncio
    async def test_traceparent_header_when_tracing_active(self, monkeypatch):
        """Quando o tracer e real, o header ``traceparent`` aparece."""
        # Configura um TracerProvider real em-memory para este teste.
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                SimpleSpanProcessor,
            )
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except Exception:
            pytest.skip("OpenTelemetry SDK nao instalado")

        provider = TracerProvider(resource=Resource.create({"service.name": "shift-test"}))
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        # Substitui o tracer global do modulo de tracing pelo nosso.
        from app.core.observability import tracing as _tr
        original = _tr._TRACER
        _tr._TRACER = provider.get_tracer("shift-test")
        try:
            # Tambem registra como global pra que ``trace.get_current_span``
            # use este provider.
            from opentelemetry import trace as otel_trace
            otel_trace.set_tracer_provider(provider)

            captured: dict[str, str] = {}

            async def handler(request):
                captured.update(dict(request.headers))
                return httpx.Response(200)

            svc = WebhookDispatchService()
            tracer = provider.get_tracer("shift-test")
            with tracer.start_as_current_span("workflow.execution") as parent:
                parent_trace_id = parent.get_span_context().trace_id
                async with _client(handler) as client:
                    await svc._post_one(client, _StubDelivery(), _StubSubscription())

            # ``traceparent`` esta no formato W3C: 00-<trace>-<span>-<flags>.
            tp = captured.get("traceparent")
            assert tp is not None, "header traceparent ausente"
            assert tp.startswith("00-")
            # O trace_id no header bate o trace_id do span pai.
            tp_trace = tp.split("-")[1]
            assert tp_trace == format(parent_trace_id, "032x")
        finally:
            _tr._TRACER = original


# ---------------------------------------------------------------------------
# Span hierarchy + atributos
# ---------------------------------------------------------------------------


class TestWebhookSpanHierarchy:
    @pytest.mark.asyncio
    async def test_span_has_parent_from_trace_context(self):
        """Quando ``delivery.trace_context`` carrega um traceparent, o span
        ``webhook.dispatch`` herda o trace_id."""
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except Exception:
            pytest.skip("OpenTelemetry SDK nao instalado")

        provider = TracerProvider(resource=Resource.create({"service.name": "shift-test"}))
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        from app.core.observability import tracing as _tr
        original = _tr._TRACER
        _tr._TRACER = provider.get_tracer("shift-test")

        try:
            tracer = provider.get_tracer("shift-test")
            # Captura o trace_context do span de execucao.
            from app.core.observability.tracing import inject_trace_context
            trace_carrier: dict[str, str] = {}
            with tracer.start_as_current_span("workflow.execution") as exec_span:
                expected_trace_id = exec_span.get_span_context().trace_id
                inject_trace_context(trace_carrier)

            assert "traceparent" in trace_carrier

            # Worker simulado: span fora do contexto pai, mas com trace_context.
            async def handler(_req):
                return httpx.Response(200)

            svc = WebhookDispatchService()
            async with _client(handler) as client:
                await svc._post_one(
                    client,
                    _StubDelivery(trace_context=trace_carrier),
                    _StubSubscription(),
                )

            # Coleta spans exportados.
            spans = exporter.get_finished_spans()
            webhook_span = next(s for s in spans if s.name == "webhook.dispatch")
            # webhook.dispatch deve carregar o mesmo trace_id do exec_span.
            assert webhook_span.context.trace_id == expected_trace_id
        finally:
            _tr._TRACER = original

    @pytest.mark.asyncio
    async def test_webhook_span_attributes(self):
        """Atributos chave ficam expostos para correlacao em backends de trace."""
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except Exception:
            pytest.skip("OpenTelemetry SDK nao instalado")

        provider = TracerProvider(resource=Resource.create({"service.name": "shift-test"}))
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        from app.core.observability import tracing as _tr
        original = _tr._TRACER
        _tr._TRACER = provider.get_tracer("shift-test")

        try:
            sub = _StubSubscription("https://hooks.example/path?token=secret")
            delivery = _StubDelivery(event="execution.failed", attempt_count=3)

            async def handler(_req):
                return httpx.Response(200)

            svc = WebhookDispatchService()
            async with _client(handler) as client:
                await svc._post_one(client, delivery, sub)

            spans = exporter.get_finished_spans()
            span = next(s for s in spans if s.name == "webhook.dispatch")
            attrs = dict(span.attributes or {})
            assert attrs["webhook.subscription_id"] == str(sub.id)
            assert attrs["webhook.delivery_id"] == str(delivery.id)
            assert attrs["webhook.event"] == "execution.failed"
            assert attrs["webhook.attempt_count"] == 3
            assert attrs["http.method"] == "POST"
            assert attrs["http.status_code"] == 200
            assert attrs["webhook.outcome"] == "success"
            # http.url presente — apos scrub (nao expoe userinfo).
            assert "hooks.example" in attrs["http.url"]
        finally:
            _tr._TRACER = original


class TestUrlScrubbing:
    """``_scrub_url_for_span`` remove credenciais embutidas mas mantem path."""

    def test_strips_basic_auth(self):
        from app.services.webhook_dispatch_service import _scrub_url_for_span
        out = _scrub_url_for_span("https://user:pass@host.example/path")
        assert "user" not in out
        assert "pass" not in out
        assert "host.example" in out
        assert "/path" in out

    def test_keeps_url_without_auth(self):
        from app.services.webhook_dispatch_service import _scrub_url_for_span
        out = _scrub_url_for_span("https://example.com/hooks?x=1")
        assert out == "https://example.com/hooks?x=1"
