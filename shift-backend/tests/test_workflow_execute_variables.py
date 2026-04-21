"""
Testes de integracao para o endpoint de execucao com variaveis (Fase 3).

Cobre:
- ExecuteWorkflowRequest: schema e defaults
- VariablesSchemaResponse: schema
- WorkflowService.run(): input_data persistido com secrets mascarados
- 400 ao faltar variavel obrigatoria
- 202 ao fornecer todos os valores
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.workflow import (
    ConnectionOptionResponse,
    ExecuteWorkflowRequest,
    VariablesSchemaResponse,
    WorkflowParam,
)


# ---------------------------------------------------------------------------
# Testes de schema
# ---------------------------------------------------------------------------

class TestExecuteWorkflowRequest:
    def test_default_empty_variable_values(self):
        req = ExecuteWorkflowRequest()
        assert req.variable_values == {}

    def test_accepts_variable_values(self):
        uid = str(uuid.uuid4())
        req = ExecuteWorkflowRequest(variable_values={"conn": uid, "label": "x"})
        assert req.variable_values["conn"] == uid
        assert req.variable_values["label"] == "x"

    def test_serializes_correctly(self):
        req = ExecuteWorkflowRequest(variable_values={"n": 42})
        data = req.model_dump()
        assert data == {"variable_values": {"n": 42}}


class TestVariablesSchemaResponse:
    def test_empty_response(self):
        resp = VariablesSchemaResponse(variables=[])
        assert resp.variables == []
        assert resp.connection_options == {}

    def test_with_variables_and_options(self):
        param = WorkflowParam(name="conn", type="connection", required=True, connection_type="postgres")
        opt = ConnectionOptionResponse(id=uuid.uuid4(), name="My DB", type="postgresql")
        resp = VariablesSchemaResponse(
            variables=[param],
            connection_options={"conn": [opt]},
        )
        assert len(resp.variables) == 1
        assert len(resp.connection_options["conn"]) == 1
        assert resp.connection_options["conn"][0].type == "postgresql"

    def test_connection_option_fields(self):
        uid = uuid.uuid4()
        opt = ConnectionOptionResponse(id=uid, name="PG Prod", type="postgresql")
        assert opt.id == uid
        assert opt.name == "PG Prod"
        assert opt.type == "postgresql"


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------

def _make_fake_db(workflow: Any, workspace_id: uuid.UUID) -> MagicMock:
    row_mock = MagicMock()
    row_mock.one_or_none.return_value = (workflow, workspace_id)

    db = MagicMock()
    db.execute = AsyncMock(return_value=row_mock)
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    captured_executions: list[Any] = []

    def _fake_add(obj: Any) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        captured_executions.append(obj)

    db.add = _fake_add
    db._captured = captured_executions

    async def _fake_flush() -> None:
        pass

    db.flush = _fake_flush
    return db


def _make_fake_session() -> MagicMock:
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    fake_session.commit = AsyncMock()
    fake_session.add = MagicMock()
    return fake_session


# ---------------------------------------------------------------------------
# Testes de integracao do servico
# ---------------------------------------------------------------------------

class TestWorkflowServicePhase3:
    """Verifica persistencia de input_data e mascaramento de secrets."""

    @pytest.mark.asyncio
    async def test_input_data_persisted_with_values(self):
        """Verifica que resolved_vars chegam em execution.input_data."""
        from app.services.workflow_service import WorkflowExecutionService

        conn_uid = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [],
            "edges": [],
            "variables": [{"name": "conn", "type": "connection", "required": True}],
        }

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        async def fake_run_workflow(**kwargs: Any) -> dict[str, Any]:
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

        with (
            patch(
                "app.services.workflow_service.connection_service.resolve_for_workflow",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.workflow_service.run_workflow", new=fake_run_workflow),
            patch(
                "app.services.workflow_service.async_session_factory",
                return_value=fake_session,
            ),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={"variable_values": {"conn": conn_uid}},
                wait=True,
            )

        # Encontra o WorkflowExecution criado no fake_db
        from app.models.workflow import WorkflowExecution
        executions = [obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)]
        assert len(executions) == 1
        exec_obj = executions[0]
        assert exec_obj.input_data is not None
        assert exec_obj.input_data["variable_values"]["conn"] == conn_uid

    @pytest.mark.asyncio
    async def test_secret_masked_in_input_data(self):
        """Verifica que variaveis do tipo secret ficam como '***' em input_data."""
        from app.services.workflow_service import WorkflowExecutionService

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [],
            "edges": [],
            "variables": [
                {"name": "api_key", "type": "secret", "required": True},
                {"name": "label", "type": "string", "required": False, "default": "default"},
            ],
        }

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        async def fake_run_workflow(**kwargs: Any) -> dict[str, Any]:
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

        with (
            patch(
                "app.services.workflow_service.connection_service.resolve_for_workflow",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.workflow_service.run_workflow", new=fake_run_workflow),
            patch(
                "app.services.workflow_service.async_session_factory",
                return_value=fake_session,
            ),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={"variable_values": {"api_key": "super-secret-token"}},
                wait=True,
            )

        from app.models.workflow import WorkflowExecution
        executions = [obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)]
        assert len(executions) == 1
        exec_obj = executions[0]
        assert exec_obj.input_data is not None
        vars_stored = exec_obj.input_data["variable_values"]
        assert vars_stored["api_key"] == "***", "Secret deve ser mascarado"
        assert vars_stored["label"] == "default", "Valor nao-secret deve ser preservado"

    @pytest.mark.asyncio
    async def test_no_input_data_when_no_variables(self):
        """Sem variaveis declaradas, input_data deve ser None."""
        from app.services.workflow_service import WorkflowExecutionService

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {"nodes": [], "edges": []}

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        async def fake_run_workflow(**kwargs: Any) -> dict[str, Any]:
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

        with (
            patch(
                "app.services.workflow_service.connection_service.resolve_for_workflow",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.workflow_service.run_workflow", new=fake_run_workflow),
            patch(
                "app.services.workflow_service.async_session_factory",
                return_value=fake_session,
            ),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={},
                wait=True,
            )

        from app.models.workflow import WorkflowExecution
        executions = [obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)]
        assert len(executions) == 1
        assert executions[0].input_data is None

    @pytest.mark.asyncio
    async def test_required_variable_missing_returns_400_context(self):
        """ValueError com 'obrigatoria' propagado — o endpoint mapeia para 400."""
        from app.services.workflow_service import WorkflowExecutionService

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [],
            "edges": [],
            "variables": [{"name": "conn", "type": "connection", "required": True}],
        }

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        service = WorkflowExecutionService()
        with pytest.raises(ValueError, match="obrigatoria"):
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={"variable_values": {}},
            )

    @pytest.mark.asyncio
    async def test_multiple_secrets_all_masked(self):
        """Todos os campos secret devem ser mascarados independentemente."""
        from app.services.workflow_service import WorkflowExecutionService

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [],
            "edges": [],
            "variables": [
                {"name": "token_a", "type": "secret", "required": True},
                {"name": "token_b", "type": "secret", "required": True},
                {"name": "label", "type": "string", "required": True},
            ],
        }

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        async def fake_run_workflow(**kwargs: Any) -> dict[str, Any]:
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

        with (
            patch(
                "app.services.workflow_service.connection_service.resolve_for_workflow",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.workflow_service.run_workflow", new=fake_run_workflow),
            patch(
                "app.services.workflow_service.async_session_factory",
                return_value=fake_session,
            ),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={
                    "variable_values": {
                        "token_a": "secret-a",
                        "token_b": "secret-b",
                        "label": "visible",
                    }
                },
                wait=True,
            )

        from app.models.workflow import WorkflowExecution
        executions = [obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)]
        vars_stored = executions[0].input_data["variable_values"]
        assert vars_stored["token_a"] == "***"
        assert vars_stored["token_b"] == "***"
        assert vars_stored["label"] == "visible"
