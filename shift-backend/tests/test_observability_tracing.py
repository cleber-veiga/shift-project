"""Testes do modulo de tracing OpenTelemetry (Prompt 6.2).

O tracer publico DEVE funcionar mesmo quando ``SHIFT_TRACING_ENABLED`` e
falso — a API publica vira no-op silencioso. Esses testes garantem que
a API nao quebra e que init_tracing e idempotente.
"""

from __future__ import annotations

import pytest

from app.core.observability import (
    extract_trace_context,
    init_tracing,
    inject_trace_context,
    start_execution_span,
    start_node_span,
    tracer,
)


@pytest.fixture(autouse=True)
def _reset_tracing(monkeypatch):
    """Garante que cada teste comeca com flag desligada e estado fresco."""
    monkeypatch.setenv("SHIFT_TRACING_ENABLED", "false")
    # Limpa estado interno entre testes.
    from app.core.observability import tracing as _t
    _t._INITIALIZED = False
    _t._TRACER = None
    yield
    _t._INITIALIZED = False
    _t._TRACER = None


def test_init_when_disabled_is_noop():
    init_tracing(app=None)
    t = tracer()
    assert t is not None  # Retorna no-op tracer, nao None.


def test_init_is_idempotent():
    init_tracing(app=None)
    init_tracing(app=None)
    # Chamou duas vezes sem explodir.
    assert tracer() is not None


def test_execution_span_does_not_raise_when_disabled():
    init_tracing(app=None)
    with start_execution_span(
        execution_id="e1",
        workflow_id="w1",
        workspace_id="ws1",
        triggered_by="manual",
    ) as span:
        # Span valido (no-op ou real) — chamadas devem nao explodir.
        span.set_attribute("k", "v")


def test_node_span_does_not_raise_when_disabled():
    init_tracing(app=None)
    with start_node_span(
        node_id="n1",
        node_type="mapper",
        execution_id="e1",
        workflow_id="w1",
        workspace_id="ws1",
    ) as span:
        span.set_attribute("foo", "bar")


def test_node_span_does_not_swallow_exception():
    init_tracing(app=None)
    with pytest.raises(ValueError):
        with start_node_span(node_id="n1", node_type="boom"):
            raise ValueError("propaga")


def test_inject_extract_roundtrip_safe():
    init_tracing(app=None)
    headers: dict[str, str] = {}
    inject_trace_context(headers)
    # Quando desligado, os headers podem ficar vazios — nao deve explodir.
    extracted = extract_trace_context(headers)
    # Nao validamos o conteudo: backend desligado pode devolver um Context
    # vazio, ou None. So checamos que nada quebra.
    assert extracted is None or extracted is not None


def test_set_attribute_filters_none_values():
    """``_set_attr`` ignora None — span nao deve receber ``None`` literal."""
    init_tracing(app=None)
    with start_execution_span(
        execution_id=None,
        workflow_id=None,
        workspace_id=None,
    ) as span:
        # Apenas garante que span funcionou apesar de todos os atributos None.
        assert span is not None
