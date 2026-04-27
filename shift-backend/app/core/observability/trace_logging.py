"""structlog processor que injeta trace context em todo log emitido.

Por que existe (Tarefa 4 do hardening 6.2/6.3)
-----------------------------------------------
Sem este processor, o operador num incidente cai em duas opcoes ruins:

1. Olha o trace no Jaeger/Tempo, copia o ``trace_id`` e tenta grep nos
   logs — funciona se cada call site lembrou de bind_context.
2. Olha o log JSON, mas nao consegue ir do log para o trace porque nao
   ha trace_id no record.

Plugando este processor no pipeline structlog, **todo** log emitido dentro
de um span ativo recebe ``trace_id`` / ``span_id`` / ``trace_flags``
automaticamente — sem mudanca em call sites.

Ordem no pipeline
-----------------
- ANTES do JSONRenderer: precisa estar no event_dict antes da serializacao
  final. Se rodar depois, JSONRenderer ja escreveu uma string e o campo
  nao aparece no JSON.
- DEPOIS do sanitize_processor: trace_id/span_id NAO sao secrets, mas
  defesa em camadas — se algum operador adicionar um padrao de match no
  sanitize que casualmente bata em hex de 32 chars, o trace_id nao ser
  pre-existente garante que sanitize nao tenta mascarar.

Performance
-----------
``trace.get_current_span()`` e barato (lookup em contextvars). Quando
nao ha span ativo, ``get_span_context().is_valid`` retorna False e o
processor nao toca o event_dict — overhead < 1us por log.

trace_flags
-----------
Campo W3C (hex de 2 chars). Bit 0 indica ``sampled``. Operadores podem
filtrar logs por ``trace_flags=01`` para ver apenas requests sampleadas
no backend de tracing — util para reduzir ruido em alta cardinalidade.
"""

from __future__ import annotations

from typing import Any


def add_trace_context(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Injeta ``trace_id`` / ``span_id`` / ``trace_flags`` quando ha span ativo.

    Idempotente — chamadas multiplas resultam no mesmo dict de saida.
    Se valores ja estao presentes (ex: bind_context manual com trace_id),
    NAO sobrescreve — preserva o que o caller deliberadamente injetou.

    Robusto a opentelemetry ausente: import tardio + try/except global
    garantem que log nunca quebra por causa de tracing.
    """
    try:
        from opentelemetry import trace as _otel_trace  # noqa: PLC0415

        span = _otel_trace.get_current_span()
        if span is None:
            return event_dict
        ctx = span.get_span_context()
        if not getattr(ctx, "is_valid", False):
            return event_dict

        # ``setdefault`` preserva o valor injetado manualmente via
        # ``bind_context(trace_id=...)`` quando o operador deliberadamente
        # esta auditando uma trace especifica.
        event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
        event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
        event_dict.setdefault("trace_flags", format(ctx.trace_flags, "02x"))
    except Exception:  # noqa: BLE001 — log nao pode quebrar por causa de tracing
        pass
    return event_dict
