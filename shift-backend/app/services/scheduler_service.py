"""
Scheduler interno para workflows com no cron.

APScheduler roda dentro do proprio processo FastAPI. Jobs sao persistidos
via ``SQLAlchemyJobStore`` no mesmo Postgres da aplicacao (tabela
``apscheduler_jobs``), entao sobrevivem a restarts.

Regra de negocio preservada:
  Um workflow tem schedule ATIVO se, e somente se:
    1. workflow.status == "published"
    2. workflow.definition contem um no do tipo "cron" com cron_expression
       nao vazia.

Em qualquer outra combinacao, o job correspondente e removido.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
)
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import bind_context, get_logger
from app.db.session import async_session_factory
from app.models.workflow import Workflow

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Scheduler singleton
# ---------------------------------------------------------------------------

jobstore = SQLAlchemyJobStore(
    url=settings.DATABASE_URL_SYNC,
    tablename="apscheduler_jobs",
)

scheduler = AsyncIOScheduler(
    jobstores={"default": jobstore},
    timezone="UTC",
    # coalesce=True  -> se varios disparos ficaram pendentes (ex.: app offline),
    #                   executa apenas UMA vez ao retomar.
    # max_instances=1 -> nunca executa o mesmo workflow em paralelo consigo
    #                   mesmo — evita corrida quando a execucao anterior ainda
    #                   nao terminou.
    # misfire_grace_time=60 -> tolera ate 60s de atraso antes de considerar
    #                   o disparo perdido.
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 60,
    },
)


# ---------------------------------------------------------------------------
# Event listeners — observabilidade do jobstore
# ---------------------------------------------------------------------------

def _on_job_executed(event: JobExecutionEvent) -> None:
    logger.info("scheduler.job_executed", job_id=event.job_id)


def _on_job_error(event: JobExecutionEvent) -> None:
    logger.error(
        "scheduler.job_error",
        job_id=event.job_id,
        exception=str(event.exception) if event.exception else None,
    )


def _on_job_missed(event: JobExecutionEvent) -> None:
    logger.warning(
        "scheduler.job_missed",
        job_id=event.job_id,
        scheduled_run_time=event.scheduled_run_time.isoformat()
        if event.scheduled_run_time
        else None,
    )


def _on_job_max_instances(event: JobExecutionEvent) -> None:
    logger.warning(
        "scheduler.job_max_instances_reached",
        job_id=event.job_id,
    )


scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
scheduler.add_listener(_on_job_max_instances, EVENT_JOB_MAX_INSTANCES)


def _job_id(workflow_id: UUID | str) -> str:
    return f"workflow-cron-{workflow_id}"


# ---------------------------------------------------------------------------
# Extracao de trigger a partir do workflow.definition
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Callback invocado pelo scheduler
# ---------------------------------------------------------------------------

async def _trigger_workflow(workflow_id: str) -> None:
    """Callback disparado pelo APScheduler quando um cron atinge o horario.

    Abre sessao propria (nao ha request HTTP) e delega para
    ``workflow_service.run``. Importamos o service dentro da funcao para
    evitar ciclo de import no bootstrap.
    """
    from app.services.workflow_service import workflow_service

    with bind_context(workflow_id=workflow_id, triggered_by="cron"):
        try:
            async with async_session_factory() as db:
                await workflow_service.run(
                    db=db,
                    workflow_id=UUID(workflow_id),
                    triggered_by="cron",
                    input_data={},
                )
                await db.commit()
            logger.info("scheduler.workflow_triggered")
        except Exception:  # noqa: BLE001
            logger.exception("scheduler.workflow_trigger_failed")


# ---------------------------------------------------------------------------
# Registro / remocao de schedules
# ---------------------------------------------------------------------------

def register_workflow_schedule(workflow: Workflow) -> bool:
    """Aplica a regra de agendamento apos mudanca num workflow.

    - published + cron valido -> cria/atualiza job
    - caso contrario          -> remove job (idempotente)

    Retorna True se um job ativo ficou registrado apos a chamada, False
    caso contrario. Nunca levanta: falhas sao logadas como warning.
    """
    workflow_id = str(workflow.id)
    cron = extract_cron_trigger(workflow.definition)
    is_published = getattr(workflow, "status", "draft") == "published"
    should_schedule = is_published and cron is not None

    try:
        if should_schedule:
            assert cron is not None
            expression, tz = cron
            trigger = CronTrigger.from_crontab(expression, timezone=tz)
            scheduler.add_job(
                _trigger_workflow,
                trigger=trigger,
                id=_job_id(workflow_id),
                args=[workflow_id],
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info(
                "scheduler.job_registered",
                workflow_id=workflow_id,
                cron_expression=expression,
                timezone=tz,
            )
            return True

        remove_workflow_schedule(workflow.id)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scheduler.register_failed",
            workflow_id=workflow_id,
            error=str(exc),
        )
        return False


def remove_workflow_schedule(workflow_id: UUID | str) -> bool:
    """Remove o job do workflow, se existir. Idempotente.

    Retorna True se havia um job e foi removido; False se nao havia.
    """
    job_id = _job_id(workflow_id)
    try:
        if scheduler.get_job(job_id) is None:
            return False
        scheduler.remove_job(job_id)
        logger.info("scheduler.job_removed", workflow_id=str(workflow_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scheduler.remove_failed",
            workflow_id=str(workflow_id),
            error=str(exc),
        )
        return False


# ---------------------------------------------------------------------------
# Status (contrato do endpoint GET /workflows/{id}/schedule)
# ---------------------------------------------------------------------------

def get_schedule_status(workflow: Workflow) -> dict[str, Any]:
    """Retorna o estado de agendamento do workflow.

    Preserva o contrato consumido pelo frontend em
    ``shift-frontend/lib/auth.ts::WorkflowScheduleStatus``.
    """
    cron = extract_cron_trigger(workflow.definition)
    is_published = getattr(workflow, "status", "draft") == "published"
    is_active = is_published and cron is not None

    return {
        "workflow_id": str(workflow.id),
        "is_active": is_active,
        "is_published": is_published,
        "has_cron_node": cron is not None,
        "cron_expression": cron[0] if cron else None,
        "timezone": cron[1] if cron else None,
    }


# ---------------------------------------------------------------------------
# Bootstrap no startup
# ---------------------------------------------------------------------------

async def bootstrap_schedules() -> None:
    """Re-sincroniza jobs a partir do estado atual dos workflows.

    Para cada workflow publicado que ainda tem no cron valido, garante
    que o job esta registrado. Workflows que deixaram de ser publicados
    ou que perderam o no cron tem seus jobs removidos.

    Roda uma unica vez no startup do FastAPI. APScheduler ja persiste
    jobs no Postgres, mas este passo reconcilia divergencias (ex.:
    workflows alterados com app offline).
    """
    async with async_session_factory() as db:
        result = await db.execute(select(Workflow))
        workflows = list(result.scalars().all())

    registered = 0
    removed = 0
    for workflow in workflows:
        cron = extract_cron_trigger(workflow.definition)
        is_published = getattr(workflow, "status", "draft") == "published"
        if is_published and cron is not None:
            if register_workflow_schedule(workflow):
                registered += 1
        else:
            if remove_workflow_schedule(workflow.id):
                removed += 1

    logger.info(
        "scheduler.bootstrapped",
        total=len(workflows),
        registered=registered,
        removed=removed,
    )
