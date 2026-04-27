"""Testes do processor structlog que injeta trace context (Tarefa 4).

Cobre:
- Log dentro de span ativo recebe ``trace_id``, ``span_id``, ``trace_flags``.
- Log fora de span continua funcionando (sem trace_id).
- Processor preserva valores existentes (``setdefault``) — operador pode
  injetar ``trace_id`` manual se quiser.
- Robusto a OpenTelemetry ausente (no-op silencioso).
"""

from __future__ import annotations

import pytest

from app.core.observability.trace_logging import add_trace_context


def _call(event_dict):
    """Invoca o processor com a assinatura structlog (logger, method, dict)."""
    return add_trace_context(None, "info", dict(event_dict))


# ---------------------------------------------------------------------------
# Fixture com OpenTelemetry SDK em-memory
# ---------------------------------------------------------------------------


@pytest.fixture
def otel_setup():
    """Configura tracer real para os testes que precisam de span ativo."""
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

    provider = TracerProvider(
        resource=Resource.create({"service.name": "shift-test-logs"}),
    )
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------


def test_log_without_span_unchanged():
    """Sem span ativo, nao adiciona campos."""
    out = _call({"event": "no span here"})
    assert "trace_id" not in out
    assert "span_id" not in out
    assert "trace_flags" not in out
    assert out["event"] == "no span here"


def test_log_inside_span_includes_trace_ids(otel_setup):
    """Dentro de span, trace_id/span_id/trace_flags vem automaticamente."""
    tracer = otel_setup.get_tracer("shift-test")
    with tracer.start_as_current_span("test.span") as span:
        ctx = span.get_span_context()
        out = _call({"event": "msg"})
        assert out["trace_id"] == format(ctx.trace_id, "032x")
        assert out["span_id"] == format(ctx.span_id, "016x")
        assert out["trace_flags"] == format(ctx.trace_flags, "02x")
        assert len(out["trace_id"]) == 32
        assert len(out["span_id"]) == 16
        assert len(out["trace_flags"]) == 2


def test_setdefault_preserves_manual_trace_id(otel_setup):
    """Se ``trace_id`` ja foi injetado manualmente, preserva."""
    tracer = otel_setup.get_tracer("shift-test")
    with tracer.start_as_current_span("test.span"):
        manual = "deadbeefcafebabedeadbeefcafebabe"
        out = _call({"event": "msg", "trace_id": manual})
        assert out["trace_id"] == manual


def test_processor_does_not_break_when_otel_absent(monkeypatch):
    """Se import falhar, o processor retorna o dict sem campos extras."""
    # Simula import falhando dentro do processor.
    import sys
    saved = sys.modules.get("opentelemetry")
    sys.modules["opentelemetry"] = None  # type: ignore[assignment]
    try:
        # Re-import para forcar o try/except interno a tropecar no import.
        out = add_trace_context(None, "info", {"event": "x"})
        # Nao explode, devolve o dict.
        assert out["event"] == "x"
    finally:
        if saved is not None:
            sys.modules["opentelemetry"] = saved
        else:
            sys.modules.pop("opentelemetry", None)


def test_processor_is_registered_in_structlog_pipeline():
    """Pipeline default do shift contem ``add_trace_context``.

    Em vez de capturar I/O (fragil com capsys + cache do structlog),
    inspeciona a lista de processors do build atual.
    """
    from app.core.logging import _build_processors
    processors = _build_processors("json")
    names = [getattr(p, "__name__", type(p).__name__) for p in processors]
    assert "add_trace_context" in names

    # Ordem: sanitize_processor antes de add_trace_context (defesa em camadas).
    sanitize_idx = names.index("sanitize_processor")
    trace_idx = names.index("add_trace_context")
    assert sanitize_idx < trace_idx, (
        "sanitize_processor deve rodar antes de add_trace_context"
    )

    # JSONRenderer (ou a equivalente) e o ULTIMO — trace context tem que
    # estar antes pra entrar no event_dict serializado.
    last = type(processors[-1]).__name__
    assert last == "JSONRenderer"
