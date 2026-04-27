"""Testes do registry central de metricas Prometheus (Prompt 6.2)."""

from __future__ import annotations

from app.core.observability.metrics import (
    EXECUTION_DURATION,
    EXECUTIONS_TOTAL,
    NODE_DURATION,
    NODE_ERRORS_TOTAL,
    NODE_ROWS_PROCESSED,
    SPAWNER_ACTIVE,
    record_execution,
    record_node,
)


def _sample_value(metric, labels: tuple) -> float | None:
    """Le o valor escalar de uma serie pelo Counter/Gauge/Histogram._count."""
    for sample in metric.collect():
        for s in sample.samples:
            if all(s.labels.get(k) == v for k, v in zip(metric._labelnames, labels)):
                return s.value
    return None


class TestRecordExecution:
    def test_observes_histogram_and_counter(self):
        ws = "ws-test-1"
        tpl = "tpl-test-1"
        before = _hist_count(EXECUTION_DURATION, (ws, tpl, "completed")) or 0
        before_total = _counter(EXECUTIONS_TOTAL, (ws, tpl, "completed")) or 0
        record_execution(
            workspace_id=ws,
            template_id=tpl,
            status="completed",
            duration_seconds=12.5,
        )
        assert _hist_count(EXECUTION_DURATION, (ws, tpl, "completed")) == before + 1
        assert _counter(EXECUTIONS_TOTAL, (ws, tpl, "completed")) == before_total + 1

    def test_handles_none_labels(self):
        # Labels None viram "unknown" — sem KeyError.
        record_execution(
            workspace_id=None,
            template_id=None,
            status="failed",
            duration_seconds=1.0,
        )
        assert _counter(EXECUTIONS_TOTAL, ("unknown", "unknown", "failed")) >= 1

    def test_negative_duration_clamps_to_zero(self):
        record_execution(
            workspace_id="ws-clamp",
            template_id="tpl-clamp",
            status="completed",
            duration_seconds=-5.0,
        )
        # A presenca da serie ja prova que nao quebrou.
        assert _hist_count(EXECUTION_DURATION, ("ws-clamp", "tpl-clamp", "completed")) >= 1


class TestRecordNode:
    def test_observes_duration_only_when_provided(self):
        before = _hist_count(NODE_DURATION, ("test_type",)) or 0
        record_node(node_type="test_type", duration_seconds=0.5)
        assert _hist_count(NODE_DURATION, ("test_type",)) == before + 1

    def test_skips_duration_when_none(self):
        before = _hist_count(NODE_DURATION, ("test_type_skip",)) or 0
        record_node(node_type="test_type_skip", rows_in=10)
        # Sem ``duration_seconds`` o histograma nao deve registrar a label
        # — ``_hist_count`` devolve None para series inexistentes.
        assert (_hist_count(NODE_DURATION, ("test_type_skip",)) or 0) == before

    def test_records_rows_in_and_out(self):
        record_node(node_type="rows_t", rows_in=100, rows_out=50)
        assert _counter(NODE_ROWS_PROCESSED, ("rows_t", "in")) >= 100
        assert _counter(NODE_ROWS_PROCESSED, ("rows_t", "out")) >= 50

    def test_zero_rows_skipped(self):
        before_in = _counter(NODE_ROWS_PROCESSED, ("zero_t", "in")) or 0
        record_node(node_type="zero_t", rows_in=0, rows_out=0)
        assert (_counter(NODE_ROWS_PROCESSED, ("zero_t", "in")) or 0) == before_in

    def test_records_error_class(self):
        before = _counter(NODE_ERRORS_TOTAL, ("err_t", "TimeoutError")) or 0
        record_node(node_type="err_t", error_class="TimeoutError")
        assert _counter(NODE_ERRORS_TOTAL, ("err_t", "TimeoutError")) == before + 1


class TestSpawnerLabels:
    def test_default_kinds_initialize_lazily(self):
        # Labels nao precisam ser pre-declaradas — incrementar e suficiente.
        SPAWNER_ACTIVE.labels("custom_kind").set(3)
        assert _gauge(SPAWNER_ACTIVE, ("custom_kind",)) == 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hist_count(hist, labels: tuple) -> float | None:
    """Le ``_count`` (numero de observacoes) de um Histogram para a tupla."""
    name = hist._name + "_count"
    for sample in hist.collect():
        for s in sample.samples:
            if s.name == name and tuple(
                s.labels.get(k) for k in hist._labelnames
            ) == labels:
                return s.value
    return None


def _counter(counter, labels: tuple) -> float | None:
    name = counter._name + "_total"
    for sample in counter.collect():
        for s in sample.samples:
            if s.name == name and tuple(
                s.labels.get(k) for k in counter._labelnames
            ) == labels:
                return s.value
    return None


def _gauge(gauge, labels: tuple) -> float | None:
    for sample in gauge.collect():
        for s in sample.samples:
            if tuple(s.labels.get(k) for k in gauge._labelnames) == labels:
                return s.value
    return None
