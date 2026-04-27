"""
Ponto de entrada da aplicacao FastAPI - Shift Backend.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.agent import router as agent_router
from app.api.v1.agent_audit import router as agent_audit_router
from app.api.v1.agent_keys import router as agent_keys_router
from app.api.v1.agent_mcp import router as agent_mcp_router
from app.api.v1.ai_chat import router as ai_chat_router
from app.api.v1.input_models import router as input_models_router
from app.api.v1.input_model_rows import router as input_model_rows_router
from app.api.v1.auth import router as auth_router
from app.api.v1.connections import router as connections_router
from app.api.v1.composite_preview import router as composite_preview_router
from app.api.v1.nodes import router as nodes_router
from app.api.v1.custom_node_definitions import router as custom_node_definitions_router
from app.api.v1.dead_letters import router as dead_letters_router
from app.api.v1.economic_groups import router as economic_groups_router
from app.api.v1.invitations import router as invitations_router
from app.api.v1.lookups import router as lookups_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.projects import router as projects_router
from app.api.v1.webhooks import router as webhook_router
from app.api.v1.webhooks_admin import router as webhook_admin_router
from app.api.v1.webhook_subscriptions import router as webhook_subscriptions_router
from app.api.v1.workflows import router as workflow_router
from app.api.v1.playground import router as playground_router
from app.api.v1.saved_queries import router as saved_queries_router
from app.api.v1.workflow_versions import router as workflow_versions_router
from app.api.v1.workflows_crud import router as workflow_crud_router
from app.api.v1.workflow_build import router as workflow_build_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.logging import get_logger
from app.core.middleware import RequestIDMiddleware
from app.core.observability import init_tracing
from app.core.rate_limit import limiter
from app.db.session import async_session_factory, engine
from app.services import webhook_service
from app.services.agent.graph.checkpointer import close_checkpointer
from app.services.agent.safety.expiration_job import register_agent_expiration_job
from app.core.config import settings
from app.services.scheduler_service import bootstrap_schedules, register_checkpoint_cleanup_job, register_extract_cache_cleanup_job, register_storage_cleanup_job, register_workflow_uploads_cleanup_job, scheduler
from app.services.webhook_dispatch_service import register_dispatch_job as register_webhook_dispatch_job
from app.services.workflow_service import cleanup_orphaned_executions
from app.api.v1.admin_storage import router as admin_storage_router
from app.api.v1.extract_cache import router as extract_cache_router
from app.services.memory_monitor import start_memory_monitor, stop_memory_monitor

logger = get_logger(__name__)


def _print_startup_banner() -> None:
    """Imprime banner ASCII no boot. Pulado quando LOG_FORMAT=json para
    nao poluir log aggregators (Loki, Datadog, etc) com linhas nao-JSON.
    """
    if settings.LOG_FORMAT != "console":
        return

    cyan = "\033[36m"
    bold = "\033[1m"
    dim = "\033[2m"
    reset = "\033[0m"

    banner = f"""
{cyan}{bold}
███████╗██╗  ██╗██╗███████╗████████╗
██╔════╝██║  ██║██║██╔════╝╚══██╔══╝
███████╗███████║██║█████╗     ██║
╚════██║██╔══██║██║██╔══╝     ██║
███████║██║  ██║██║██║        ██║
╚══════╝╚═╝  ╚═╝╚═╝╚═╝        ╚═╝
{reset}{dim}  Plataforma de integracao, migracao e automacao de dados
  Backend v0.1.0{reset}
"""
    print(banner, flush=True)


_print_startup_banner()


async def _build_session_cleanup_loop(interval_seconds: float = 300.0) -> None:
    """Remove build sessions expiradas em loop."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.services.build_session_service import build_session_service as _bss
            removed = await _bss.cleanup_expired()
            if removed:
                logger.info("build_session.cleanup.purged", count=removed)
        except Exception:  # noqa: BLE001
            logger.exception("build_session.cleanup_failed")


async def _purge_webhook_captures_loop(interval_seconds: float = 300.0) -> None:
    """Limpa capturas expiradas da tabela webhook_test_captures em loop."""
    while True:
        try:
            async with async_session_factory() as session:
                removed = await webhook_service.purge_expired_captures(session)
                if removed:
                    logger.info("webhook.capture.purged", count=removed)
        except Exception:  # noqa: BLE001
            logger.exception("webhook.capture.purge_failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerenciador de ciclo de vida: startup e shutdown."""
    _ = app
    await cleanup_orphaned_executions()
    scheduler.start()
    await bootstrap_schedules()
    register_storage_cleanup_job()
    register_checkpoint_cleanup_job()
    register_extract_cache_cleanup_job()
    register_workflow_uploads_cleanup_job()
    register_webhook_dispatch_job(scheduler)
    if settings.AGENT_ENABLED:
        register_agent_expiration_job(
            scheduler,
            interval_minutes=settings.AGENT_EXPIRATION_JOB_INTERVAL_MINUTES,
        )
    purge_task = asyncio.create_task(
        _purge_webhook_captures_loop(), name="webhook-capture-purge"
    )
    cleanup_task = asyncio.create_task(
        _build_session_cleanup_loop(), name="build-session-cleanup"
    )
    start_memory_monitor()
    # Seed das gauges db_pool_* — garante que /metrics ja exiba as series
    # mesmo antes da primeira execucao usar engines do cache.
    from app.services.db.engine_cache import refresh_metrics as _seed_metrics
    _seed_metrics()
    # Pre-warm do pool de sandbox quando habilitado (Prompt 2.2). Falha
    # silenciosamente quando docker daemon nao esta acessivel — code_node
    # entao usa cold path.
    try:
        from app.services.sandbox import init_default_pool
        _sandbox_pool = init_default_pool()
        if _sandbox_pool is not None:
            logger.info(
                "sandbox.pool.prewarmed",
                idle=_sandbox_pool.idle_count,
                target=_sandbox_pool._target_idle,  # type: ignore[attr-defined]
            )
    except Exception as _exc:  # noqa: BLE001
        logger.warning("sandbox.pool.startup_failed", error=str(_exc))
    logger.info("scheduler.started")
    try:
        yield
    finally:
        purge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await purge_task
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task
        await stop_memory_monitor()
        # Mata containers warm — sem isso, eles ficariam vivos ate o daemon
        # docker fazer GC. Bloqueia o shutdown ate todos morrerem.
        try:
            from app.services.sandbox import stop_all_pools
            stop_all_pools()
        except Exception as _exc:  # noqa: BLE001
            logger.warning("sandbox.pool.stop_failed", error=str(_exc))
        scheduler.shutdown(wait=True)
        logger.info("scheduler.stopped")
        await close_checkpointer()
        await engine.dispose()


app = FastAPI(
    title="Shift Backend",
    description="Plataforma de integracao, migracao e automacao de dados",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Rate limiter (slowapi) ---
# Registra o limiter no state para os decorators @limiter.limit nas rotas
# e instala o handler que converte RateLimitExceeded em 429.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Correlation ID ---
# Adicionado ANTES do CORS para que o request_id esteja disponivel
# em qualquer middleware/handler que emita log durante a request.
app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Expoe o request_id e o Retry-After (emitido pelo handler de 429).
    expose_headers=["X-Request-ID", "Retry-After"],
)

# --- Prometheus metrics ---
# Instrumenta latencia, throughput, in-progress e tamanhos de request/response
# por rota. Endpoint /metrics (scrape pelo Prometheus) e excluido das metricas
# para nao poluir com auto-scrape.
_instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics", "/health"],
)
# Antes de cada coleta, sincroniza as gauges db_pool_* com o estado atual
# dos pools no engine_cache (size / checked_out / overflow por workspace e
# tipo de banco). Atualizar no scrape evita ter que mexer nas gauges em
# todo get_engine.
from app.services.db.engine_cache import (  # noqa: E402 — boot-time only
    register_metric_callbacks,
)
register_metric_callbacks(_instrumentator)
_instrumentator.instrument(app).expose(app, endpoint="/metrics", tags=["sistema"])

# --- OpenTelemetry tracing ---
# Inicializa apos instanciar `app` (precisa do FastAPI para instrumentar
# request handlers) e depois do Instrumentator para que /metrics nao
# entre como span. Quando ``SHIFT_TRACING_ENABLED`` esta off, init_tracing
# vira no-op — zero overhead em dev.
init_tracing(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(connections_router, prefix="/api/v1")
app.include_router(composite_preview_router, prefix="/api/v1")
app.include_router(nodes_router, prefix="/api/v1")
app.include_router(custom_node_definitions_router, prefix="/api/v1")
app.include_router(dead_letters_router, prefix="/api/v1")
app.include_router(economic_groups_router, prefix="/api/v1")
app.include_router(lookups_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(webhook_admin_router, prefix="/api/v1")
app.include_router(webhook_subscriptions_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
# IMPORTANTE: workflow_versions_router precisa vir antes do workflow_crud_router
# porque define rotas literais como `/workflows/callable` que colidem com o
# padrão `/workflows/{workflow_id}` registrado pelo crud — sem essa ordem,
# "callable" seria capturado como workflow_id e rejeitado como UUID inválido.
app.include_router(workflow_versions_router, prefix="/api/v1")
app.include_router(workflow_crud_router, prefix="/api/v1")
app.include_router(workflow_build_router, prefix="/api/v1")
app.include_router(playground_router, prefix="/api/v1")
app.include_router(saved_queries_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(agent_audit_router, prefix="/api/v1")
app.include_router(agent_keys_router, prefix="/api/v1")
app.include_router(agent_mcp_router, prefix="/api/v1")
app.include_router(ai_chat_router, prefix="/api/v1")
app.include_router(input_models_router, prefix="/api/v1")
app.include_router(input_model_rows_router, prefix="/api/v1")
app.include_router(invitations_router, prefix="/api/v1")
app.include_router(admin_storage_router, prefix="/api/v1")
app.include_router(extract_cache_router, prefix="/api/v1")


@app.get("/health", tags=["sistema"])
async def health_check() -> dict[str, str]:
    """Endpoint de verificacao de saude da aplicacao."""
    return {"status": "ok"}
