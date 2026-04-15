"""
Servico de workflows: submissao para o Prefect e consulta de status.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Project
from app.models.workflow import Workflow, WorkflowExecution
from app.schemas.workflow import ExecutionResponse, ExecutionStatusResponse
from app.services.connection_service import connection_service


class WorkflowExecutionService:
    """Logica de negocio para execucao e acompanhamento de workflows."""

    async def run(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        triggered_by: str = "manual",
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResponse:
        """Cria um registro de execucao e submete o workflow ao Prefect."""
        result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
        workflow = result.scalar_one_or_none()

        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' nao encontrado.")

        if workflow.workspace_id is not None:
            workspace_id = workflow.workspace_id
        else:
            workspace_id = await self._get_workspace_id_by_project(db, workflow.project_id)
            if workspace_id is None:
                raise ValueError(
                    f"Projeto associado ao workflow '{workflow_id}' nao encontrado."
                )

        resolved_connections = await connection_service.resolve_for_workflow(
            db,
            workflow.definition,
            project_id=workflow.project_id,
            workspace_id=workspace_id,
        )

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            status="PENDING",
        )
        db.add(execution)
        await db.flush()

        prefect_flow_run_id = await self._submit_to_prefect(
            execution_id=execution.id,
            workflow_id=workflow.id,
            workflow_definition=workflow.definition,
            triggered_by=triggered_by,
            input_data=input_data or {},
            resolved_connections=resolved_connections,
        )

        execution.prefect_flow_run_id = prefect_flow_run_id
        execution.status = "SUBMITTED" if prefect_flow_run_id is not None else "PENDING"
        await db.flush()

        return ExecutionResponse(
            execution_id=execution.id,
            prefect_flow_run_id=prefect_flow_run_id,
            status=execution.status,
        )

    async def execute_workflow(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResponse:
        """Mantem compatibilidade com a rota manual existente."""
        return await self.run(
            db=db,
            workflow_id=workflow_id,
            triggered_by="manual",
            input_data=input_data,
        )

    async def _submit_to_prefect(
        self,
        execution_id: UUID,
        workflow_id: UUID,
        workflow_definition: dict[str, Any],
        triggered_by: str,
        input_data: dict[str, Any],
        resolved_connections: dict[str, str] | None = None,
    ) -> UUID | None:
        """Submete o workflow para o Prefect via run_deployment."""
        from prefect.deployments import run_deployment

        try:
            flow_run = await run_deployment(
                name=settings.PREFECT_DEPLOYMENT_NAME,
                parameters={
                    "execution_id": str(execution_id),
                    "workflow_id": str(workflow_id),
                    "workflow_payload": workflow_definition,
                    "triggered_by": triggered_by,
                    "input_data": input_data,
                    "resolved_connections": resolved_connections or {},
                },
                timeout=0,
            )
            return flow_run.id
        except Exception:
            return None

    async def get_execution_status(
        self,
        db: AsyncSession,
        execution_id: UUID,
    ) -> ExecutionStatusResponse | None:
        """Consulta o status de uma execucao de workflow."""
        stmt = select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
        result = await db.execute(stmt)
        execution = result.scalar_one_or_none()

        if execution is None:
            return None

        return ExecutionStatusResponse(
            execution_id=execution.id,
            status=execution.status,
            result=execution.result,
            error_message=execution.error_message,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
        )

    async def _get_workspace_id_by_project(
        self,
        db: AsyncSession,
        project_id: UUID,
    ) -> UUID | None:
        result = await db.execute(
            select(Project.workspace_id).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()


workflow_service = WorkflowExecutionService()
