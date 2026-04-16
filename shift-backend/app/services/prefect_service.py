"""
Servico para gerenciamento de deployments e schedules no Prefect.

O FastAPI deve chamar schedule_workflow quando um workflow com trigger
cron for salvo ou atualizado. Quando o no cron for removido, o endpoint
de salvamento deve chamar remove_schedule para limpar o deployment.
"""

from typing import Any
from uuid import UUID

from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import DeploymentUpdate
from prefect.client.schemas.filters import FlowFilter, FlowFilterName
from prefect.client.schemas.schedules import CronSchedule
from prefect.exceptions import ObjectNotFound

from app.core.config import settings


class PrefectDeploymentService:
    """Gerencia deployments e schedules no Prefect 3.x."""

    def __init__(self, flow_name: str | None = None) -> None:
        self.flow_name = flow_name or settings.PREFECT_FLOW_NAME
        self.base_deployment_name = settings.PREFECT_DEPLOYMENT_NAME

    async def schedule_workflow(
        self,
        workflow_id: UUID,
        cron_expression: str,
        timezone: str,
    ) -> dict[str, Any]:
        """
        Cria ou atualiza um deployment com schedule cron para o workflow.

        A mesma flow principal e reutilizada, recebendo workflow_id e
        triggered_by='cron' como parametros padrao.
        """
        flow_id = await self._get_flow_id(self.flow_name)
        if flow_id is None:
            raise ValueError(f"Flow '{self.flow_name}' nao encontrada no Prefect.")

        deployment_name = self._build_deployment_name(workflow_id)
        parameters: dict[str, Any] = {
            "workflow_id": str(workflow_id),
            "triggered_by": "cron",
            "input_data": {},
        }
        schedule = CronSchedule(cron=cron_expression, timezone=timezone)
        base_deployment = await self._read_base_deployment()
        work_pool_name = self._safe_attr(base_deployment, "work_pool_name") or settings.PREFECT_WORK_POOL_NAME or None

        async with get_client() as client:
            try:
                deployment = await client.read_deployment_by_name(
                    f"{self.flow_name}/{deployment_name}"
                )
                await client.update_deployment(
                    deployment_id=deployment.id,
                    deployment=DeploymentUpdate(
                        parameters=parameters,
                        tags=self._build_tags(
                            workflow_id, self._safe_attr(base_deployment, "tags")
                        ),
                        paused=False,
                        work_pool_name=work_pool_name,
                        work_queue_name=self._safe_attr(
                            base_deployment, "work_queue_name"
                        ),
                        job_variables=self._safe_attr(
                            base_deployment, "job_variables"
                        ),
                        path=self._safe_attr(base_deployment, "path"),
                        entrypoint=self._safe_attr(base_deployment, "entrypoint"),
                        storage_document_id=self._safe_attr(
                            base_deployment, "storage_document_id"
                        ),
                        infrastructure_document_id=self._safe_attr(
                            base_deployment, "infrastructure_document_id"
                        ),
                        enforce_parameter_schema=False,
                    ),
                )
                deployment_id = deployment.id
                updated = True
            except ObjectNotFound:
                deployment_id = await client.create_deployment(
                    flow_id=flow_id,
                    name=deployment_name,
                    parameters=parameters,
                    tags=self._build_tags(
                        workflow_id, self._safe_attr(base_deployment, "tags")
                    ),
                    paused=False,
                    work_pool_name=work_pool_name,
                    work_queue_name=self._safe_attr(
                        base_deployment, "work_queue_name"
                    ),
                    job_variables=self._safe_attr(
                        base_deployment, "job_variables"
                    ),
                    path=self._safe_attr(base_deployment, "path"),
                    entrypoint=self._safe_attr(base_deployment, "entrypoint"),
                    storage_document_id=self._safe_attr(
                        base_deployment, "storage_document_id"
                    ),
                    infrastructure_document_id=self._safe_attr(
                        base_deployment, "infrastructure_document_id"
                    ),
                    pull_steps=self._safe_attr(base_deployment, "pull_steps"),
                    enforce_parameter_schema=False,
                )
                updated = False

            existing_schedules = await client.read_deployment_schedules(deployment_id)
            for existing_schedule in existing_schedules:
                await client.delete_deployment_schedule(
                    deployment_id=deployment_id,
                    schedule_id=existing_schedule.id,
                )

            created_schedules = await client.create_deployment_schedules(
                deployment_id=deployment_id,
                schedules=[(schedule, True)],
            )

        return {
            "deployment_id": str(deployment_id),
            "deployment_name": deployment_name,
            "flow_name": self.flow_name,
            "cron_expression": cron_expression,
            "timezone": timezone,
            "schedule_ids": [str(item.id) for item in created_schedules],
            "updated": updated,
        }

    async def remove_schedule(self, workflow_id: UUID) -> bool:
        """
        Remove o deployment de agendamento associado ao workflow.

        O endpoint PUT /workflows/{id} deve chamar este metodo quando o
        grafo salvo nao contiver mais um no cron ativo.
        """
        deployment_name = self._build_deployment_name(workflow_id)

        async with get_client() as client:
            try:
                deployment = await client.read_deployment_by_name(
                    f"{self.flow_name}/{deployment_name}"
                )
            except ObjectNotFound:
                return False

            await client.delete_deployment(deployment.id)
            return True

    async def _get_flow_id(self, flow_name: str) -> UUID | None:
        """Busca o ID da flow principal pelo nome registrado no Prefect."""
        async with get_client() as client:
            flows = await client.read_flows(
                flow_filter=FlowFilter(name=FlowFilterName(any_=[flow_name])),
                limit=1,
            )

        if not flows:
            return None

        return flows[0].id

    async def _read_base_deployment(self) -> Any | None:
        """
        Le o deployment base usado nas execucoes on-demand do Shift.

        Se ele nao existir, ainda tentamos criar o deployment agendado
        apenas com flow_id e parametros, mantendo compatibilidade.
        """
        async with get_client() as client:
            try:
                return await client.read_deployment_by_name(self.base_deployment_name)
            except ObjectNotFound:
                return None

    @staticmethod
    def _build_deployment_name(workflow_id: UUID) -> str:
        """Gera o nome do deployment dedicado ao workflow."""
        return f"shift-cron-{workflow_id}"

    @staticmethod
    def _build_tags(workflow_id: UUID, base_tags: list[str] | None) -> list[str]:
        """Combina tags base com metadados do workflow agendado."""
        combined_tags = set(base_tags or [])
        combined_tags.update({"shift", "cron", str(workflow_id)})
        return sorted(combined_tags)

    @staticmethod
    def _safe_attr(source: Any | None, field_name: str) -> Any | None:
        """Le um atributo opcional do deployment base sem quebrar o fallback."""
        if source is None:
            return None
        return getattr(source, field_name, None)


prefect_deployment_service = PrefectDeploymentService()
