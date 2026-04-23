"""
Testes da camada de tools do Platform Agent.

Abordagem: testes unitarios com mocks dos servicos externos.
Nenhuma conexao real com banco de dados e necessaria.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.agent.base import AgentNotFoundError, AgentPermissionError
from app.services.agent.context import UserContext
from app.services.agent.tools.connection_tools import get_connection
from app.services.agent.tools.registry import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    execute_tool,
    requires_approval,
)
from app.services.agent.tools.workflow_tools import execute_workflow, list_workflows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx(**kwargs) -> UserContext:
    defaults: dict = {
        "user_id": uuid4(),
        "workspace_id": uuid4(),
        "project_id": None,
        "workspace_role": "MANAGER",
        "project_role": "EDITOR",
        "organization_id": uuid4(),
        "organization_role": "MEMBER",
    }
    defaults.update(kwargs)
    return UserContext(**defaults)


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1. Permissoes: VIEWER nao pode chamar execute_workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_cannot_execute_workflow(mock_db: AsyncMock) -> None:
    ctx = make_ctx(workspace_role="VIEWER", project_role=None)
    with pytest.raises(AgentPermissionError):
        await execute_workflow(db=mock_db, ctx=ctx, workflow_id=str(uuid4()))


@pytest.mark.asyncio
async def test_consultant_without_project_role_cannot_execute_workflow(
    mock_db: AsyncMock,
) -> None:
    ctx = make_ctx(workspace_role="CONSULTANT", project_role=None)
    with pytest.raises(AgentPermissionError):
        await execute_workflow(db=mock_db, ctx=ctx, workflow_id=str(uuid4()))


@pytest.mark.asyncio
async def test_manager_can_bypass_project_role_check(mock_db: AsyncMock) -> None:
    """Workspace MANAGER herda EDITOR em todos os projetos — nao deve levantar permissao."""
    ctx = make_ctx(workspace_role="MANAGER", project_role=None)

    wf = MagicMock()
    wf.id = uuid4()
    wf.workspace_id = ctx.workspace_id
    wf.project_id = None

    execution_response = MagicMock()
    execution_response.execution_id = uuid4()
    execution_response.status = "RUNNING"

    with patch(
        "app.services.agent.tools.workflow_tools.workflow_crud_service"
    ) as mock_crud, patch(
        "app.services.agent.tools.workflow_tools.workflow_service"
    ) as mock_svc:
        mock_crud.get = AsyncMock(return_value=wf)
        mock_svc.run = AsyncMock(return_value=execution_response)

        result = await execute_workflow(
            db=mock_db, ctx=ctx, workflow_id=str(wf.id)
        )

    assert str(execution_response.execution_id) in result


# ---------------------------------------------------------------------------
# 2. Escopo: workflow de outro workspace -> AgentNotFoundError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_from_other_workspace_raises_not_found(
    mock_db: AsyncMock,
) -> None:
    ctx = make_ctx(workspace_role="CONSULTANT", project_role="EDITOR")

    wf = MagicMock()
    wf.workspace_id = uuid4()  # workspace diferente do ctx
    wf.project_id = None

    with patch(
        "app.services.agent.tools.workflow_tools.workflow_crud_service"
    ) as mock_crud, patch(
        "app.services.agent.tools.workflow_tools.b2b_service"
    ) as mock_b2b:
        mock_crud.get = AsyncMock(return_value=wf)
        mock_b2b.get_project_for_user = AsyncMock(return_value=None)

        with pytest.raises(AgentNotFoundError):
            await execute_workflow(
                db=mock_db, ctx=ctx, workflow_id=str(uuid4())
            )


# ---------------------------------------------------------------------------
# 3. Happy path: list_workflows retorna workflows do workspace correto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_workflows_returns_names(mock_db: AsyncMock) -> None:
    ctx = make_ctx(workspace_role="VIEWER")

    wf1 = MagicMock()
    wf1.name = "Migracao Totvs"
    wf1.status = "published"
    wf1.id = uuid4()

    wf2 = MagicMock()
    wf2.name = "Exportar Clientes"
    wf2.status = "draft"
    wf2.id = uuid4()

    with patch(
        "app.services.agent.tools.workflow_tools.workflow_crud_service"
    ) as mock_crud:
        mock_crud.list_for_workspace = AsyncMock(return_value=[wf1, wf2])
        result = await list_workflows(db=mock_db, ctx=ctx)

    assert "Migracao Totvs" in result
    assert "Exportar Clientes" in result
    assert "published" in result
    assert "draft" in result


@pytest.mark.asyncio
async def test_list_workflows_empty(mock_db: AsyncMock) -> None:
    ctx = make_ctx(workspace_role="VIEWER")

    with patch(
        "app.services.agent.tools.workflow_tools.workflow_crud_service"
    ) as mock_crud:
        mock_crud.list_for_workspace = AsyncMock(return_value=[])
        result = await list_workflows(db=mock_db, ctx=ctx)

    assert "Nenhum" in result


# ---------------------------------------------------------------------------
# 4. Sanitizacao: get_connection nao retorna campos sensiveis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_connection_never_returns_password(mock_db: AsyncMock) -> None:
    ctx = make_ctx(workspace_role="VIEWER")

    conn = MagicMock()
    conn.id = uuid4()
    conn.name = "Producao PostgreSQL"
    conn.type = "postgresql"
    conn.host = "db.empresa.com"
    conn.port = 5432
    conn.database = "erp"
    conn.username = "readonly"
    conn.password = "SUPER_SECRET_PASSWORD_123"
    conn.is_public = True
    conn.workspace_id = ctx.workspace_id
    conn.project_id = None
    conn.created_by_id = ctx.user_id

    with patch(
        "app.services.agent.tools.connection_tools.connection_service"
    ) as mock_svc:
        mock_svc.get = AsyncMock(return_value=conn)
        result = await get_connection(
            db=mock_db, ctx=ctx, connection_id=str(conn.id)
        )

    assert "SUPER_SECRET_PASSWORD_123" not in result
    assert "Producao PostgreSQL" in result
    assert "db.empresa.com" in result
    assert "readonly" in result


@pytest.mark.asyncio
async def test_get_connection_out_of_scope_not_found(mock_db: AsyncMock) -> None:
    ctx = make_ctx(workspace_role="VIEWER")

    conn = MagicMock()
    conn.id = uuid4()
    conn.workspace_id = uuid4()  # workspace diferente
    conn.project_id = None
    conn.is_public = True
    conn.created_by_id = uuid4()

    with patch(
        "app.services.agent.tools.connection_tools.connection_service"
    ) as mock_svc, patch(
        "app.services.agent.tools.connection_tools.b2b_service"
    ) as mock_b2b:
        mock_svc.get = AsyncMock(return_value=conn)
        mock_b2b.get_project_for_user = AsyncMock(return_value=None)

        with pytest.raises(AgentNotFoundError):
            await get_connection(
                db=mock_db, ctx=ctx, connection_id=str(conn.id)
            )


# ---------------------------------------------------------------------------
# 5. Registry: requires_approval e correto para cada tool
# ---------------------------------------------------------------------------


def test_requires_approval_destructive_tools() -> None:
    assert requires_approval("execute_workflow") is True
    assert requires_approval("cancel_execution") is True
    assert requires_approval("create_project") is True
    assert requires_approval("trigger_webhook_manually") is True


def test_requires_approval_readonly_tools() -> None:
    assert requires_approval("list_workflows") is False
    assert requires_approval("get_workflow") is False
    assert requires_approval("get_execution_status") is False
    assert requires_approval("list_recent_executions") is False
    assert requires_approval("list_projects") is False
    assert requires_approval("get_project") is False
    assert requires_approval("list_project_members") is False
    assert requires_approval("list_connections") is False
    assert requires_approval("get_connection") is False
    assert requires_approval("test_connection") is False
    assert requires_approval("list_webhooks") is False


def test_requires_approval_unknown_tool_returns_false() -> None:
    assert requires_approval("ferramenta_inexistente") is False


# ---------------------------------------------------------------------------
# 6. Dispatcher: tool desconhecida retorna string amigavel, nao levanta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_unknown_name_returns_string(mock_db: AsyncMock) -> None:
    ctx = make_ctx()
    result = await execute_tool(
        "tool_inexistente", {}, db=mock_db, user_context=ctx
    )
    assert isinstance(result, str)
    assert "tool_inexistente" in result or "desconhecida" in result.lower()


@pytest.mark.asyncio
async def test_execute_tool_permission_error_returns_string(
    mock_db: AsyncMock,
) -> None:
    ctx = make_ctx(workspace_role="VIEWER", project_role=None)
    result = await execute_tool(
        "execute_workflow",
        {"workflow_id": str(uuid4())},
        db=mock_db,
        user_context=ctx,
    )
    assert isinstance(result, str)
    assert "Permissao" in result or "permissao" in result.lower()


# ---------------------------------------------------------------------------
# 7. Validacao: schemas do registry estao completos e validos
# ---------------------------------------------------------------------------


def test_all_tools_have_valid_schemas() -> None:
    assert len(TOOL_REGISTRY) == 27
    for name, entry in TOOL_REGISTRY.items():
        schema = entry["schema"]
        assert schema["type"] == "function", f"{name}: type != 'function'"
        fn = schema["function"]
        assert fn["name"] == name, f"{name}: schema name mismatch"
        assert len(fn["description"]) > 30, f"{name}: description muito curta"
        assert "parameters" in fn, f"{name}: sem parameters"
        assert "required" in fn["parameters"], f"{name}: sem required"


def test_tool_schemas_list_matches_registry() -> None:
    assert len(TOOL_SCHEMAS) == len(TOOL_REGISTRY)
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    registry_names = set(TOOL_REGISTRY.keys())
    assert schema_names == registry_names
