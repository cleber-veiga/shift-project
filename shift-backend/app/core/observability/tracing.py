"""Configuracao de tracing OpenTelemetry para o Shift.

Modelo
------
- Um span por **execucao de workflow** (root quando disparado por API/cron;
  child quando ja recebido com ``traceparent``).
- Um span por **no** dentro da execucao — child do span de execucao.
- Atributos em ambos: ``workspace_id``, ``execution_id``, ``template_id`` /
  ``workflow_id``, ``node_id``, ``node_type``.
- Status: ``OK`` em sucesso, ``ERROR`` com record_exception em falha.

Export
------
Por padrao usamos OTLP/HTTP — qualquer backend compativel funciona
(Jaeger collector com OTLP, Tempo, Honeycomb, Grafana Cloud, etc.).
Endpoint configurado via env:

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` (ex: ``http://localhost:4318``)
- ``OTEL_EXPORTER_OTLP_HEADERS`` (autenticacao, ex: ``api-key=xxx``)
- ``OTEL_SERVICE_NAME`` (default: ``shift-backend``)
- ``SHIFT_TRACING_ENABLED`` (default: ``false``; ligar so quando o backend
  estiver instalado)

Quando desabilitado, ``init_tracing`` instala um tracer no-op — toda a
API publica continua funcionando mas nao gera spans nem rede.

Propagacao
----------
Aceita ``traceparent`` e ``tracestate`` (W3C Trace Context) na entrada
de qualquer request HTTP via ``FastAPIInstrumentor``. A funcao
``inject_trace_context`` produz os headers para chamadas saida (ex:
shift-backend → shift-compute hipotetico, ou webhook do usuario que
queira correlacionar).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Mapping


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------


_TRACER: Any | None = None
_INITIALIZED = False


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def init_tracing(app: Any | None = None) -> None:
    """Inicializa o tracer e instrumenta libs comuns.

    Idempotente — chamadas subsequentes viram no-op. Chame uma vez no
    boot (lifespan do FastAPI). Quando ``SHIFT_TRACING_ENABLED`` esta
    falso, instala apenas um tracer no-op para que ``tracer().start_span``
    nao quebre.

    ``app`` e o ``FastAPI`` para instrumentar requests; pode ser None se
    o caller quiser instrumentar manualmente depois.
    """
    global _TRACER, _INITIALIZED  # noqa: PLW0603

    if _INITIALIZED:
        return
    _INITIALIZED = True

    enabled = _is_truthy(os.getenv("SHIFT_TRACING_ENABLED"))
    if not enabled:
        # Tracer no-op — API publica funciona, mas nao gera spans.
        try:
            from opentelemetry import trace as otel_trace  # noqa: PLC0415
            _TRACER = otel_trace.get_tracer(__name__)
        except Exception:  # noqa: BLE001
            # opentelemetry nao instalado: cai no shim local.
            _TRACER = _NoopTracer()
        return

    try:
        from opentelemetry import trace as otel_trace  # noqa: PLC0415
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
            BatchSpanProcessor,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tracing.init_failed_imports",
            extra={"error": str(exc)},
        )
        _TRACER = _NoopTracer()
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "shift-backend")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    try:
        # OTLPSpanExporter resolve o endpoint a partir das envs OTEL_*
        # quando ``endpoint`` e None — mantemos o fallback para nao sobrescrever.
        exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tracing.exporter_init_failed",
            extra={"error": str(exc), "endpoint": endpoint},
        )

    otel_trace.set_tracer_provider(provider)
    _TRACER = otel_trace.get_tracer("shift-backend")

    # Instrumentacao de bibliotecas — falhas sao tolerantes (instrument
    # e best-effort para nao impedir o boot).
    if app is not None:
        _safe_instrument_fastapi(app)
    _safe_instrument_sqlalchemy()
    _safe_instrument_httpx()
    logger.info("tracing.initialized", extra={"service_name": service_name})


def _safe_instrument_fastapi(app: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import (  # noqa: PLC0415
            FastAPIInstrumentor,
        )
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics,/health")
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracing.fastapi_instrument_failed", extra={"error": str(exc)})


def _safe_instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import (  # noqa: PLC0415
            SQLAlchemyInstrumentor,
        )
        SQLAlchemyInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracing.sqlalchemy_instrument_failed", extra={"error": str(exc)})


def _safe_instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import (  # noqa: PLC0415
            HTTPXClientInstrumentor,
        )
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracing.httpx_instrument_failed", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


def tracer() -> Any:
    """Devolve o tracer ativo. Cria um no-op se ``init_tracing`` nao rodou."""
    if _TRACER is None:
        return _NoopTracer()
    return _TRACER


@contextmanager
def start_execution_span(
    *,
    execution_id: str | None,
    workflow_id: str | None,
    workspace_id: str | None,
    triggered_by: str = "manual",
) -> Iterator[Any]:
    """Abre um span de execucao de workflow.

    Atributos: ``execution_id``, ``workflow_id`` (= ``template_id`` no Shift),
    ``workspace_id``, ``triggered_by``. Sucesso/erro determinado pelo bloco
    ``with`` — se uma excecao escapa, marcamos com ``record_exception``.
    """
    span_cm = tracer().start_as_current_span("workflow.execution")
    with span_cm as span:
        try:
            _set_attr(span, "execution_id", execution_id)
            _set_attr(span, "workflow_id", workflow_id)
            _set_attr(span, "template_id", workflow_id)
            _set_attr(span, "workspace_id", workspace_id)
            _set_attr(span, "triggered_by", triggered_by)
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


@contextmanager
def start_node_span(
    *,
    node_id: str,
    node_type: str,
    execution_id: str | None = None,
    workflow_id: str | None = None,
    workspace_id: str | None = None,
) -> Iterator[Any]:
    """Abre um span de processamento de no, child do span ativo (execucao)."""
    span_cm = tracer().start_as_current_span(f"node.{node_type}")
    with span_cm as span:
        try:
            _set_attr(span, "node_id", node_id)
            _set_attr(span, "node_type", node_type)
            _set_attr(span, "execution_id", execution_id)
            _set_attr(span, "workflow_id", workflow_id)
            _set_attr(span, "template_id", workflow_id)
            _set_attr(span, "workspace_id", workspace_id)
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """Injeta ``traceparent`` / ``tracestate`` no dict de headers.

    Use ao chamar servicos downstream para propagar a trace ID. Operacao
    in-place (e tambem retorna ``headers`` para chaining).
    """
    try:
        from opentelemetry.propagate import inject  # noqa: PLC0415
        inject(headers)
    except Exception as exc:  # noqa: BLE001
        logger.debug("tracing.inject_failed", extra={"error": str(exc)})
    return headers


def extract_trace_context(headers: Mapping[str, str]) -> Any:
    """Extrai contexto de trace de headers de entrada.

    Retorna um Context do opentelemetry — passe para ``trace.set_span_in_context``
    ou para ``tracer.start_as_current_span(context=ctx)`` para que o span
    novo seja child do trace upstream.
    """
    try:
        from opentelemetry.propagate import extract  # noqa: PLC0415
        return extract(dict(headers))
    except Exception as exc:  # noqa: BLE001
        logger.debug("tracing.extract_failed", extra={"error": str(exc)})
        return None


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _set_attr(span: Any, key: str, value: Any) -> None:
    if value is None or span is None:
        return
    set_attr = getattr(span, "set_attribute", None)
    if set_attr is None:
        return
    try:
        set_attr(key, str(value))
    except Exception:  # noqa: BLE001
        pass


def _record_exception(span: Any, exc: BaseException) -> None:
    if span is None:
        return
    try:
        record = getattr(span, "record_exception", None)
        if record is not None:
            record(exc)
        # ``set_status`` espera StatusCode.ERROR — importamos lazy para nao
        # quebrar caso opentelemetry nao esteja instalado.
        try:
            from opentelemetry.trace import Status, StatusCode  # noqa: PLC0415
            span.set_status(Status(StatusCode.ERROR, str(exc)))
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# No-op tracer (fallback quando opentelemetry nao esta disponivel)
# ---------------------------------------------------------------------------


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401
        pass

    def record_exception(self, exc: BaseException) -> None:  # noqa: D401
        pass

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: D401
        pass

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, _name: str, **_kwargs: Any) -> Iterator[_NoopSpan]:
        yield _NoopSpan()
