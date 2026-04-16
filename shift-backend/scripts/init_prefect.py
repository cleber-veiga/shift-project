"""
Registra o deployment 'shift-workflow-runner' no pool 'shift-pool'.
Executar UMA ÚNICA VEZ (ou ao resetar o ambiente Prefect).

    make init-prefect

Pré-requisito: servidor Prefect rodando (make prefect).
"""
import asyncio
import os
import sys

from app.core.config import settings

POOL = settings.PREFECT_WORK_POOL_NAME or "shift-pool"
FLOW_NAME = settings.PREFECT_FLOW_NAME          # "dynamic-runner"
DEPLOYMENT_NAME = "shift-workflow-runner"
ENTRYPOINT = "app/orchestration/flows/dynamic_runner.py:run_workflow"


async def setup() -> None:
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.actions import DeploymentUpdate
    from prefect.client.schemas.filters import FlowFilter, FlowFilterName
    from prefect.exceptions import ObjectNotFound

    async with get_client() as client:
        # ── 1. Garante que o flow está registrado ──────────────────────────
        # O flow é registrado automaticamente ao ser servido ou implantado.
        # Se ainda não existir, criamos aqui para o deployment funcionar.
        flows = await client.read_flows(
            flow_filter=FlowFilter(name=FlowFilterName(any_=[FLOW_NAME])),
            limit=1,
        )
        if flows:
            flow_id = flows[0].id
            print(f"✓ Flow '{FLOW_NAME}' encontrado (id={flow_id}).")
        else:
            flow_id = await client.create_flow_from_name(FLOW_NAME)
            print(f"✓ Flow '{FLOW_NAME}' registrado (id={flow_id}).")

        # ── 2. Cria ou atualiza o deployment base ──────────────────────────
        full_name = f"{FLOW_NAME}/{DEPLOYMENT_NAME}"
        try:
            deployment = await client.read_deployment_by_name(full_name)
            await client.update_deployment(
                deployment_id=deployment.id,
                deployment=DeploymentUpdate(
                    work_pool_name=POOL,
                    paused=False,
                ),
            )
            print(f"✓ Deployment '{full_name}' atualizado → pool '{POOL}'.")
        except ObjectNotFound:
            await client.create_deployment(
                flow_id=flow_id,
                name=DEPLOYMENT_NAME,
                work_pool_name=POOL,
                path=os.getcwd(),
                entrypoint=ENTRYPOINT,
                paused=False,
                enforce_parameter_schema=False,
            )
            print(f"✓ Deployment '{full_name}' criado no pool '{POOL}'.")


asyncio.run(setup())
print(f"\nSetup concluído! Próximo passo: make worker")
