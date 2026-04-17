"""
Servico de workflows: dispatch local via asyncio e consulta de status.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func as sa_func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import bind_context, get_logger
from app.db.session import async_session_factory
from app.models import Project
from app.models.workflow import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.orchestration.flows.dynamic_runner import EventSink, run_workflow
from app.schemas.workflow import ExecutionResponse, ExecutionStatusResponse
from app.services import execution_registry
from app.services.connection_service import connection_service
from app.services.workflow.nodes.exceptions import NodeProcessingError, NodeProcessingSkipped


logger = get_logger(__name__)


class WorkflowExecutionService:
    """Logica de negocio para execucao e acompanhamento de workflows."""

    async def run(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        *,
        triggered_by: str = "manual",
        input_data: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
        mode: str | None = None,
        wait: bool = False,
        target_node_id: str | None = None,
    ) -> ExecutionResponse:
        """Unico entrypoint de execucao de workflow deste servico.

        Faz todo o preflight (lookup do workflow, resolucao de conexoes,
        criacao da ``WorkflowExecution``) na sessao recebida, comita, e
        dispara o runner:

        - ``wait=False`` (padrao): agenda ``_run_and_persist`` como task
          em background e registra no ``execution_registry``. Usado pela
          rota HTTP de execucao manual e pelo cron scheduler.
        - ``wait=True``: executa ``_run_and_persist`` inline e so retorna
          apos o termino. Usado pela rota SSE (workflow_test_service),
          que precisa consumir eventos sincronamente.

        Parametros de observabilidade/apresentacao:

        - ``event_sink``: callback async que recebe cada evento do runner
          (repassado direto a ``run_workflow``). Tipico uso e empurrar
          para uma ``asyncio.Queue`` que e drenada para SSE.
        - ``mode``: ``"production"`` | ``"test"`` | ``None``. Quando
          ``None``, deriva de ``workflow.status`` (``"published"`` ->
          production, outros -> test).
        - ``target_node_id``: recorta o grafo aos ancestrais (inclusive)
          do alvo antes de executar. Usado pelo botao "testar ate aqui".
        """
        # 1 query: busca workflow + workspace_id via LEFT JOIN com project
        result = await db.execute(
            select(
                Workflow,
                sa_func.coalesce(Workflow.workspace_id, Project.workspace_id).label(
                    "effective_workspace_id"
                ),
            )
            .outerjoin(Project, Project.id == Workflow.project_id)
            .where(Workflow.id == workflow_id)
        )
        row = result.one_or_none()

        if row is None:
            raise ValueError(f"Workflow '{workflow_id}' nao encontrado.")

        workflow = row[0]
        workspace_id = row[1]
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

        effective_mode = mode or (
            "production" if workflow.status == "published" else "test"
        )

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            status="RUNNING",
            triggered_by=triggered_by,
            started_at=datetime.now(timezone.utc),
        )
        db.add(execution)
        await db.flush()

        # Captura dados antes de liberar a sessao — a execucao roda em background
        # (ou inline) e abre sua propria sessao para persistir o resultado.
        execution_id = execution.id
        definition = workflow.definition
        exec_status = execution.status
        await db.commit()

        run_coro = self._run_and_persist(
            execution_id=execution_id,
            workflow_id=workflow.id,
            workflow_definition=definition,
            triggered_by=triggered_by,
            input_data=input_data or {},
            resolved_connections=resolved_connections,
            event_sink=event_sink,
            mode=effective_mode,
            target_node_id=target_node_id,
        )

        if wait:
            # Roda inline — quem chamou (SSE) ja esta consumindo eventos
            # em paralelo via event_sink/queue.
            await run_coro
        else:
            task = asyncio.create_task(
                run_coro,
                name=f"workflow-execution-{execution_id}",
            )
            await execution_registry.register(execution_id, task)

        return ExecutionResponse(
            execution_id=execution_id,
            status=exec_status,
        )

    async def run_with_events(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        *,
        event_sink: EventSink,
        triggered_by: str = "manual",
        input_data: dict[str, Any] | None = None,
        mode: str | None = None,
        target_node_id: str | None = None,
    ) -> ExecutionResponse:
        """Acucar para a rota SSE: ``run(..., wait=True, event_sink=...)``.

        Um ``event_sink`` nao faz sentido com ``wait=False`` na pratica
        (quem consumiria?), entao consolidamos ambos aqui.
        """
        return await self.run(
            db=db,
            workflow_id=workflow_id,
            triggered_by=triggered_by,
            input_data=input_data,
            event_sink=event_sink,
            mode=mode,
            wait=True,
            target_node_id=target_node_id,
        )

    async def execute_workflow(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResponse:
        """Mantem compatibilidade com a rota POST /execute (HTTP publica)."""
        return await self.run(
            db=db,
            workflow_id=workflow_id,
            triggered_by="api",
            input_data=input_data,
            mode="production",
        )

    async def _run_and_persist(
        self,
        execution_id: UUID,
        workflow_id: UUID,
        workflow_definition: dict[str, Any],
        triggered_by: str,
        input_data: dict[str, Any],
        resolved_connections: dict[str, str] | None,
        event_sink: EventSink | None = None,
        mode: str = "production",
        target_node_id: str | None = None,
    ) -> None:
        """
        Roda o workflow e persiste o estado final em uma sessao propria —
        nao compartilhamos a sessao do request HTTP. Quando disparado em
        task, a limpeza do registry e feita via ``add_done_callback`` em
        ``run()``.
        """
        result: dict[str, Any] | None = None
        error: str | None = None
        cancelled = False

        with bind_context(execution_id=str(execution_id), workflow_id=str(workflow_id)):
            try:
                result = await run_workflow(
                    workflow_payload=workflow_definition,
                    workflow_id=str(workflow_id),
                    triggered_by=triggered_by,
                    input_data=input_data,
                    execution_id=str(execution_id),
                    resolved_connections=resolved_connections,
                    event_sink=event_sink,
                    mode=mode,
                    target_node_id=target_node_id,
                )
            except asyncio.CancelledError:
                cancelled = True
                logger.info("execution.cancelled")
                # Nao re-raise: ja persistimos como CANCELLED abaixo. Re-raise
                # subiria a excecao ate o event loop do FastAPI sem nenhum
                # handler util.
            except (NodeProcessingError, NodeProcessingSkipped) as exc:
                error = str(exc)
                logger.error("execution.failed", error=error)
            except Exception as exc:  # noqa: BLE001 — precisamos marcar FAILED no DB
                error = f"{type(exc).__name__}: {exc}"
                logger.exception("execution.unexpected_error")
            finally:
                await self._persist_final_state(
                    execution_id=execution_id,
                    result=result,
                    error=error,
                    cancelled=cancelled,
                )

    async def _persist_final_state(
        self,
        execution_id: UUID,
        result: dict[str, Any] | None,
        error: str | None,
        cancelled: bool,
    ) -> None:
        """Abre sessao propria e persiste status final da execucao.

        Alem do registro em ``workflow_executions``, grava uma linha em
        ``workflow_node_executions`` por no despachado (sucesso, falha ou
        skip) usando os eventos emitidos pelo ``dynamic_runner`` em
        ``result["node_executions"]``. Isso mantem paridade com o
        ``workflow_test_service``, que ja persiste o mesmo detalhamento.
        """
        async with async_session_factory() as session:
            stmt = select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
            row = await session.execute(stmt)
            execution = row.scalar_one_or_none()
            if execution is None:
                logger.warning(
                    "execution.persist_missing", execution_id=str(execution_id)
                )
                return

            execution.completed_at = datetime.now(timezone.utc)

            if cancelled:
                execution.status = "CANCELLED"
                execution.error_message = error or "Execution cancelled by user."
            elif error is not None:
                execution.status = "FAILED"
                execution.error_message = error
            elif result is None:
                execution.status = "FAILED"
                execution.error_message = "Workflow finished without a result."
            else:
                status = result.get("status", "completed")
                if status == "completed":
                    execution.status = "COMPLETED"
                elif status == "failed":
                    execution.status = "FAILED"
                    execution.error_message = result.get("error")
                elif status == "aborted":
                    execution.status = "ABORTED"
                    execution.error_message = result.get("reason")
                else:
                    execution.status = status.upper()
                # Nao duplica node_executions no JSONB de result — ja virou
                # linhas da tabela workflow_node_executions abaixo.
                execution.result = {
                    k: v for k, v in result.items() if k != "node_executions"
                }

            # Persiste eventos por no, se o runner emitiu algum.
            if result is not None:
                for evt in result.get("node_executions") or []:
                    session.add(
                        self._build_node_execution_record(execution_id, evt)
                    )

            await session.commit()

    @staticmethod
    def _build_node_execution_record(
        execution_id: UUID,
        evt: dict[str, Any],
    ) -> WorkflowNodeExecution:
        """Constroi uma linha ``WorkflowNodeExecution`` a partir do evento do runner.

        Blindado contra chaves faltantes / tipos inesperados para nunca
        bloquear a persistencia do ``WorkflowExecution`` principal por
        causa de um evento malformado.
        """
        def _int_or_none(value: Any) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        return WorkflowNodeExecution(
            execution_id=execution_id,
            node_id=str(evt.get("node_id") or ""),
            node_type=str(evt.get("node_type") or "unknown"),
            label=evt.get("label"),
            status=str(evt.get("status") or "success"),
            duration_ms=int(evt.get("duration_ms") or 0),
            row_count_in=_int_or_none(evt.get("row_count_in")),
            row_count_out=_int_or_none(evt.get("row_count_out")),
            output_summary=evt.get("output_summary") if isinstance(evt.get("output_summary"), dict) else None,
            error_message=evt.get("error_message"),
            started_at=evt.get("started_at"),
            completed_at=evt.get("completed_at"),
        )

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
            triggered_by=execution.triggered_by,
            result=execution.result,
            error_message=execution.error_message,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
        )


workflow_service = WorkflowExecutionService()


# Chave fixa para pg_try_advisory_lock. Valor arbitrario — precisa apenas
# ser constante e unico dentro do banco para este cleanup. Usamos um inteiro
# derivado de "shift.cleanup.orphaned_executions".
_CLEANUP_ADVISORY_LOCK_KEY = 8472_103_945_611_337


async def cleanup_orphaned_executions(
    heartbeat_stale_minutes: int = 2,
) -> int:
    """
    Marca como ``CRASHED`` execucoes presas em ``RUNNING`` cujo
    ``updated_at`` (heartbeat) esta mais antigo que ``heartbeat_stale_minutes``.

    Roda no startup do FastAPI: se o processo anterior morreu enquanto
    rodava workflows, essas execucoes nunca receberam ``completed_at`` e
    ficariam eternamente em RUNNING. Aqui fechamos o loop.

    Seguranca em multi-replica
    --------------------------
    Usa ``pg_try_advisory_xact_lock`` para garantir que apenas UMA replica
    executa o cleanup simultaneamente. Se outra ja tem o lock, retornamos
    imediatamente com 0 — sem bloquear o startup. O lock e liberado no
    commit/rollback da transacao.

    Retorna o numero de execucoes reclassificadas.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=heartbeat_stale_minutes)
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        # pg_try_advisory_xact_lock retorna bool; lock liberado no commit.
        lock_result = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": _CLEANUP_ADVISORY_LOCK_KEY},
        )
        acquired = bool(lock_result.scalar())
        if not acquired:
            logger.info("execution.cleanup.skipped_locked_by_peer")
            await session.rollback()
            return 0

        result = await session.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.status == "RUNNING")
            .where(WorkflowExecution.updated_at < cutoff)
            .values(
                status="CRASHED",
                error_message="Execucao interrompida por crash do servidor.",
                completed_at=now,
                updated_at=now,
            )
        )
        await session.commit()
        count = result.rowcount or 0

    if count:
        logger.warning("execution.cleanup.crashed_marked", count=count)
    else:
        logger.info("execution.cleanup.none")
    return count
