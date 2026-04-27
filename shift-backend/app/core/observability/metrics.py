"""Registry central de metricas Prometheus do runner Shift.

Escopo
------
Define metricas de **execucao de workflow** e **processamento de no**
— os outros componentes (db_pool_*, sandbox_pool_*, streaming_*) ja
declaram suas series junto do codigo que as atualiza, porque o
acoplamento e mais forte ali.

Series expostas em /metrics:

- ``execution_duration_seconds`` (Histogram)
    Labels: ``workspace_id``, ``template_id``, ``status``.
    ``status`` ∈ {completed, failed, cancelled, aborted}.
- ``shift_executions_total`` (Counter)
    Labels: ``workspace_id``, ``template_id``, ``status``.
    Util pra calcular ``rate(shift_executions_total[5m])`` e taxa de erro
    sem ler o ``_count`` do histograma (mais barato no Prometheus).
- ``node_duration_seconds`` (Histogram)
    Labels: ``node_type``.
- ``node_rows_processed`` (Counter)
    Labels: ``node_type``, ``direction`` (``in`` | ``out``).
- ``node_errors_total`` (Counter)
    Labels: ``node_type``, ``error_class``.
- ``spawner_active`` (Gauge)
    Labels: ``spawner_kind`` (``execution`` | ``project_slot`` | ``sandbox`` | ...).
    Recursos atualmente em uso por cada tipo de spawner.
- ``spawner_spawned_total`` (Counter)
    Labels: ``spawner_kind``.
- ``spawner_errors_total`` (Counter)
    Labels: ``spawner_kind``, ``error_class``.

Cardinalidade
-------------
``workspace_id`` e ``template_id`` sao IDs de UUID — explodir cardinalidade
nao e gratis. Em /metrics, o Prometheus roda OK ate algumas centenas de
milhares de series por instancia. Deployments multi-tenant maduros
costumam:

1. Aplicar relabeling no Prometheus (drop de IDs antigos),
2. Ou usar metric_relabel_configs com ``source_labels: [workspace_id]`` para
   manter apenas top N workspaces.

Aqui nao limitamos cardinalidade — preferimos series detalhadas e
deixamos a politica para a infra. Em deployments single-tenant isso
nao e problema; em multi-tenant grande, vale revisitar.

Buckets
-------
Os Histograms usam buckets escolhidos para os perfis tipicos do Shift:

- ``execution_duration_seconds``: 1s, 5s, 30s, 1min, 5min, 15min, 1h, 2h.
- ``node_duration_seconds``: 10ms, 100ms, 500ms, 1s, 5s, 30s, 2min, 10min.

Buckets cobrem desde os processadores rapidos (mapper, filter ~ms) ate
extracao SQL particionada (~minutos) sem precisao excessiva.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import Counter, Gauge, Histogram


# ---------------------------------------------------------------------------
# Metricas de execucao de workflow
# ---------------------------------------------------------------------------


_EXECUTION_BUCKETS = (
    1.0, 5.0, 15.0, 30.0,
    60.0, 120.0, 300.0,
    600.0, 1200.0, 3600.0, 7200.0,
)

EXECUTION_DURATION = Histogram(
    "execution_duration_seconds",
    "Duracao de uma execucao de workflow (incluindo tempo de fila — medido "
    "pelo runner, do start ao final).",
    ("workspace_id", "template_id", "status"),
    buckets=_EXECUTION_BUCKETS,
)

EXECUTIONS_TOTAL = Counter(
    "shift_executions_total",
    "Contador de execucoes finalizadas por status. Mais barato para taxa "
    "de erro do que ler ``_count`` do histograma.",
    ("workspace_id", "template_id", "status"),
)


# ---------------------------------------------------------------------------
# Metricas de processamento de no
# ---------------------------------------------------------------------------


_NODE_BUCKETS = (
    0.01, 0.05, 0.1, 0.5,
    1.0, 5.0, 30.0,
    60.0, 120.0, 300.0, 600.0,
)

NODE_DURATION = Histogram(
    "node_duration_seconds",
    "Duracao de processamento de um no individual.",
    ("node_type",),
    buckets=_NODE_BUCKETS,
)

NODE_ROWS_PROCESSED = Counter(
    "node_rows_processed",
    "Linhas processadas por no, separadas por direcao "
    "(``in`` = entrada, ``out`` = saida).",
    ("node_type", "direction"),
)

NODE_ERRORS_TOTAL = Counter(
    "node_errors_total",
    "Erros levantados por processadores de no.",
    ("node_type", "error_class"),
)


# ---------------------------------------------------------------------------
# Metricas de spawners (concorrencia / pools)
# ---------------------------------------------------------------------------
#
# Centraliza Gauges/Counters genericos para qualquer "spawner" — o codigo de
# concorrencia do runner (acquire_execution_slot/release) e qualquer outro
# componente que aloque slots por categoria pode incrementar/decrementar
# essas series.
#
# Mantemos generico (label ``spawner_kind``) em vez de gauge por tipo
# porque novos spawners sao adicionados ao longo do projeto (queue por
# execucao, slot por projeto, sandbox, etc.) e nao queremos espalhar
# Gauge() declaradas em N modulos.


SPAWNER_ACTIVE = Gauge(
    "spawner_active",
    "Slots de spawner atualmente ocupados, por tipo "
    "(``execution`` = global; ``project_slot`` = por projeto; ``sandbox`` = "
    "container de codigo; outros componentes podem registrar tipos novos).",
    ("spawner_kind",),
)

SPAWNER_SPAWNED_TOTAL = Counter(
    "spawner_spawned_total",
    "Total de aquisicoes bem-sucedidas de slots de spawner.",
    ("spawner_kind",),
)

SPAWNER_ERRORS_TOTAL = Counter(
    "spawner_errors_total",
    "Erros / timeouts ao tentar adquirir slot de spawner.",
    ("spawner_kind", "error_class"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _label(value: Any) -> str:
    """Converte qualquer valor para uma label segura (string nao-vazia).

    Prometheus aceita string vazia mas isso polui agregacoes (``{"":"x"}``).
    Substitui None / "" por ``"unknown"``.
    """
    if value is None:
        return "unknown"
    s = str(value).strip()
    return s if s else "unknown"


def record_execution(
    *,
    workspace_id: Any,
    template_id: Any,
    status: str,
    duration_seconds: float,
) -> None:
    """Registra metricas de fim de execucao.

    Idempotente em relacao a labels — chame ``status`` exatamente uma vez
    por execucao ao final (qualquer terminal: completed/failed/cancelled/
    aborted). Duplicar a chamada vai dobrar o counter de execucoes.
    """
    ws = _label(workspace_id)
    tpl = _label(template_id)
    st = _label(status)
    EXECUTION_DURATION.labels(ws, tpl, st).observe(max(0.0, duration_seconds))
    EXECUTIONS_TOTAL.labels(ws, tpl, st).inc()


def record_node(
    *,
    node_type: Any,
    duration_seconds: float | None = None,
    rows_in: int | None = None,
    rows_out: int | None = None,
    error_class: str | None = None,
) -> None:
    """Registra metricas de fim de processamento de um no.

    Todos os argumentos sao opcionais para que o caller chame uma vez ao
    final do no (success ou error) e a funcao decida quais series tocar.

    - ``duration_seconds``: sempre observado quando informado.
    - ``rows_in``/``rows_out``: incrementam o counter ``node_rows_processed``
      apenas quando o valor e > 0 (evita inflar series com 0).
    - ``error_class``: nome curto da classe da excecao (ex: ``NodeProcessingError``,
      ``TimeoutError``); incrementa ``node_errors_total``.
    """
    nt = _label(node_type)
    if duration_seconds is not None:
        NODE_DURATION.labels(nt).observe(max(0.0, duration_seconds))
    if rows_in and rows_in > 0:
        NODE_ROWS_PROCESSED.labels(nt, "in").inc(rows_in)
    if rows_out and rows_out > 0:
        NODE_ROWS_PROCESSED.labels(nt, "out").inc(rows_out)
    if error_class:
        NODE_ERRORS_TOTAL.labels(nt, _label(error_class)).inc()
