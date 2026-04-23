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
from app.api.v1.workflows import router as workflow_router
from app.api.v1.playground import router as playground_router
from app.api.v1.saved_queries import router as saved_queries_router
from app.api.v1.workflow_versions import router as workflow_versions_router
from app.api.v1.workflows_crud import router as workflow_crud_router
from app.api.v1.workflow_build import router as workflow_build_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.logging import get_logger
from app.core.middleware import RequestIDMiddleware
from app.core.rate_limit import limiter
from app.db.session import async_session_factory, engine
from app.services import webhook_service
from app.services.agent.graph.checkpointer import close_checkpointer
from app.services.agent.safety.expiration_job import register_agent_expiration_job
from app.core.config import settings
from app.services.scheduler_service import bootstrap_schedules, scheduler
from app.services.workflow_service import cleanup_orphaned_executions

logger = get_logger(__name__)


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
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics", "/health"],
).instrument(app).expose(app, endpoint="/metrics", tags=["sistema"])

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


@app.get("/health", tags=["sistema"])
async def health_check() -> dict[str, str]:
    """Endpoint de verificacao de saude da aplicacao."""
    return {"status": "ok"}
