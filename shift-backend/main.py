"""
Ponto de entrada da aplicacao FastAPI - Shift Backend.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.ai_chat import router as ai_chat_router
from app.api.v1.input_models import router as input_models_router
from app.api.v1.input_model_rows import router as input_model_rows_router
from app.api.v1.auth import router as auth_router
from app.api.v1.connections import router as connections_router
from app.api.v1.economic_groups import router as economic_groups_router
from app.api.v1.invitations import router as invitations_router
from app.api.v1.lookups import router as lookups_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.projects import router as projects_router
from app.api.v1.webhooks import router as webhook_router
from app.api.v1.workflows import router as workflow_router
from app.api.v1.playground import router as playground_router
from app.api.v1.saved_queries import router as saved_queries_router
from app.api.v1.workflows_crud import router as workflow_crud_router
from app.api.v1.workspaces import router as workspaces_router
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerenciador de ciclo de vida: startup e shutdown."""
    _ = app
    yield
    await engine.dispose()


app = FastAPI(
    title="Shift Backend",
    description="Plataforma de integracao, migracao e automacao de dados",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(connections_router, prefix="/api/v1")
app.include_router(economic_groups_router, prefix="/api/v1")
app.include_router(lookups_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(workflow_crud_router, prefix="/api/v1")
app.include_router(playground_router, prefix="/api/v1")
app.include_router(saved_queries_router, prefix="/api/v1")
app.include_router(ai_chat_router, prefix="/api/v1")
app.include_router(input_models_router, prefix="/api/v1")
app.include_router(input_model_rows_router, prefix="/api/v1")
app.include_router(invitations_router, prefix="/api/v1")


@app.get("/health", tags=["sistema"])
async def health_check() -> dict[str, str]:
    """Endpoint de verificacao de saude da aplicacao."""
    return {"status": "ok"}
