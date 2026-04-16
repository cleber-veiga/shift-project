"""
Sincroniza agendamentos cron entre o banco local (Workflow) e o Prefect.

Regra de negocio:
  Um workflow possui schedule ativo no Prefect se, e somente se:
    1. workflow.status == "published"
    2. workflow.definition contem um no do tipo "cron" com cron_expression
       nao vazia

Em qualquer outra combinacao, o deployment correspondente e removido.

Erros de comunicacao com o Prefect sao registrados como warning e NAO
propagam excecao — salvar o workflow nunca deve falhar por indisponibilidade
do orquestrador. O status de sincronizacao e retornado num dict.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.models.workflow import Workflow
from app.services.prefect_service import prefect_deployment_service

logger = logging.getLogger(__name__)


def extract_cron_trigger(definition: Any) -> tuple[str, str] | None:
    """Localiza um no cron com configuracao valida no definition JSON.

    Retorna (cron_expression, timezone) para o PRIMEIRO no cron valido
    encontrado. Retorna None se nenhum no cron estiver presente ou
    configurado corretamente.
    """
    if not isinstance(definition, dict):
        return None

    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return None

    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "cron":
            continue

        data = node.get("data")
        if not isinstance(data, dict):
            continue

        expression = data.get("cron_expression")
        if not isinstance(expression, str):
            continue
        expression = expression.strip()
        if not expression:
            continue

        timezone = data.get("timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            timezone = "UTC"
        else:
            timezone = timezone.strip()

        return expression, timezone

    return None


async def sync_workflow_schedule(workflow: Workflow) -> dict[str, Any]:
    """Aplica a regra de agendamento apos uma mudanca no workflow.

    Fluxo:
      - published + tem no cron valido -> cria/atualiza deployment no Prefect
      - qualquer outro caso -> remove deployment (idempotente)

    Nunca levanta excecao — falhas do Prefect sao capturadas e reportadas
    no dict de retorno:
      {
        "action": "scheduled" | "removed" | "noop" | "error",
        "cron_expression": str | None,
        "timezone": str | None,
        "error": str | None,
      }
    """
    cron = extract_cron_trigger(workflow.definition)
    is_published = getattr(workflow, "status", "draft") == "published"
    should_schedule = is_published and cron is not None

    result: dict[str, Any] = {
        "action": "noop",
        "cron_expression": cron[0] if cron else None,
        "timezone": cron[1] if cron else None,
        "error": None,
    }

    try:
        if should_schedule:
            assert cron is not None
            expression, timezone = cron
            deployment = await prefect_deployment_service.schedule_workflow(
                workflow.id, expression, timezone
            )
            result["action"] = "scheduled"
            result["deployment"] = {
                "deployment_id": deployment.get("deployment_id"),
                "deployment_name": deployment.get("deployment_name"),
            }
        else:
            removed = await prefect_deployment_service.remove_schedule(workflow.id)
            result["action"] = "removed" if removed else "noop"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Falha ao sincronizar schedule do workflow %s: %s",
            workflow.id,
            exc,
        )
        result["action"] = "error"
        result["error"] = str(exc)

    return result


async def remove_workflow_schedule(workflow_id: UUID) -> dict[str, Any]:
    """Remove o deployment do workflow (usado em DELETE).

    Nunca levanta excecao — apenas registra warning em caso de falha.
    """
    try:
        removed = await prefect_deployment_service.remove_schedule(workflow_id)
        return {"action": "removed" if removed else "noop", "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Falha ao remover schedule do workflow %s: %s",
            workflow_id,
            exc,
        )
        return {"action": "error", "error": str(exc)}
