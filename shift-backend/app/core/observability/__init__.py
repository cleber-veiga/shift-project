"""Camada central de observabilidade do Shift.

Reune metricas Prometheus, tracing OpenTelemetry e sanitizacao de logs
em um unico ponto de import. Codigo de aplicacao deve preferir importar
daqui — em vez de tocar nos modulos de cada subsistema diretamente — para
que o boot da observabilidade fique concentrado em ``main.py``.

Submodulos:

- ``metrics``    : registry central de Histograms/Counters/Gauges (execution_*,
                   node_*, queue_*, spawner_*, sandbox_pool_*, db_pool_*).
                   Os de pool de DB / sandbox / streaming continuam definidos
                   junto do componente que os atualiza (engine_cache,
                   sandbox/pool, streaming/bounded_chunk_queue) — aqui ficam
                   apenas os que pertencem ao runner.
- ``tracing``    : configuracao do OpenTelemetry, instrumentacao de FastAPI/
                   SQLAlchemy/HTTPX e helpers para criar spans com atributos
                   padronizados de execucao.
- ``log_sanitizer``: structlog processor que mascara campos com nome
                   sugestivo (password, token, secret, api_key, ...) e
                   strings claramente sensiveis (Bearer tokens, fernet keys).
                   Plugado em ``app.core.logging`` no boot.
"""

from app.core.observability.metrics import (  # noqa: F401
    EXECUTION_DURATION,
    EXECUTIONS_TOTAL,
    NODE_DURATION,
    NODE_ERRORS_TOTAL,
    NODE_ROWS_PROCESSED,
    SPAWNER_ACTIVE,
    SPAWNER_ERRORS_TOTAL,
    SPAWNER_SPAWNED_TOTAL,
    record_execution,
    record_node,
)
from app.core.observability.tracing import (  # noqa: F401
    extract_trace_context,
    init_tracing,
    inject_trace_context,
    start_execution_span,
    start_node_span,
    tracer,
)
from app.core.observability.log_sanitizer import (  # noqa: F401
    SECRET_KEY_NAMES,
    sanitize_event_dict,
    sanitize_processor,
)
from app.core.observability.trace_logging import (  # noqa: F401
    add_trace_context,
)
