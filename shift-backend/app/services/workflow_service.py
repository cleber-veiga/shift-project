"""
Servico de workflows: dispatch local via asyncio e consulta de status.
"""

import asyncio
import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func as sa_func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import bind_context, get_logger
from app.services import checkpoint_service
from app.services.execution_log_service import ExecutionLogBuffer
from app.db.session import async_session_factory
from app.models import Project
from app.models.workflow import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.orchestration.flows.dynamic_runner import (
    ConcurrencyLimitError,
    EventSink,
    acquire_execution_slot,
    release_execution_slot,
    run_workflow,
)
from app.schemas.workflow import ExecutionResponse, ExecutionStatusResponse
from app.services import execution_registry
from app.services.connection_service import connection_service
from app.services.workflow.nodes.exceptions import NodeProcessingError, NodeProcessingSkipped


logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers para resolucao de variaveis do workflow
# ---------------------------------------------------------------------------

_VARS_SUB_RE = re.compile(r"\{\{\s*vars\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _substitute_vars_in_definition(
    definition: dict[str, Any],
    resolved_vars: dict[str, Any],
) -> dict[str, Any]:
    """Substitui {{vars.X}} em toda a definicao antes de iniciar a execucao.

    A substituicao integral garante que connection_id com template ja chega
    como UUID string para resolve_for_workflow e _inject_connection_string.
    Campos como url/query que usem {{vars.X}} tambem ficam resolvidos, mas
    context['vars'] ainda e injetado para uso dinamico em processors.
    """
    if not resolved_vars:
        return definition

    def _walk(obj: Any) -> Any:
        if isinstance(obj, str):
            full = _VARS_SUB_RE.fullmatch(obj)
            if full:
                val = resolved_vars.get(full.group(1))
                return val if val is not None else obj
            return _VARS_SUB_RE.sub(
                lambda m: str(resolved_vars[m.group(1)])
                if m.group(1) in resolved_vars
                else m.group(0),
                obj,
            )
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(item) for item in obj]
        return obj

    return _walk(copy.deepcopy(definition))


def _coerce_variable_value(name: str, declared_type: str, value: Any) -> Any:
    """Coerce e valida um valor fornecido contra o tipo declarado da variavel."""
    if declared_type in ("string", "secret"):
        return str(value)
    if declared_type == "integer":
        try:
            return int(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Variavel '{name}' deve ser inteiro.") from exc
    if declared_type == "number":
        try:
            return float(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Variavel '{name}' deve ser numero.") from exc
    if declared_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True
            if value.lower() in ("false", "0", "no"):
                return False
        raise ValueError(f"Variavel '{name}' deve ser booleano (true/false).")
    if declared_type == "connection":
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ValueError(
                f"Variavel '{name}' deve ser um UUID de conexao valido."
            ) from exc
    if declared_type == "file_upload":
        return str(value)
    # object, array, table_reference — aceita sem coercao
    return value


def _collect_referenced_var_names(definition: dict[str, Any] | None) -> set[str]:
    """Nomes de variaveis usadas via {{vars.X}} nos nos ativos da definicao.

    Nos com ``data.enabled == False`` sao ignorados (mesmo criterio do schema
    endpoint) — variaveis usadas so em nos desativados nao bloqueiam execucao.
    """
    if not definition:
        return set()
    found: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            for m in _VARS_SUB_RE.finditer(obj):
                found.add(m.group(1))
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    for node in definition.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") or {}
        if isinstance(data, dict) and data.get("enabled") is False:
            continue
        scrubbed = {k: v for k, v in data.items() if k != "pinnedOutput"} if isinstance(data, dict) else data
        _walk(scrubbed)
    return found


def _extract_subworkflow_ref(
    node: dict[str, Any],
) -> tuple[UUID, Any] | None:
    """Extrai ``(workflow_id, version_spec)`` de um no que invoca sub-workflow.

    Cobre ``call_workflow`` e ``loop`` — ambos disparam um sub-fluxo via
    ``_invoke_subworkflow``, entao as variaveis declaradas por esse sub-fluxo
    tambem precisam aparecer como herdadas no pai.

    - ``call_workflow``: ``data.workflow_id`` + ``data.version``
    - ``loop``         : ``data.workflow_id`` + ``data.workflow_version``

    Devolve ``None`` se o no esta desativado, nao tem workflow alvo, ou o UUID
    nao e valido.
    """
    if not isinstance(node, dict):
        return None
    node_type = node.get("type")
    if node_type not in ("call_workflow", "loop"):
        return None
    data = node.get("data") or {}
    if not isinstance(data, dict) or data.get("enabled") is False:
        return None
    sub_wf_id_raw = data.get("workflow_id")
    if not sub_wf_id_raw:
        return None
    try:
        sub_wf_id = UUID(str(sub_wf_id_raw))
    except (ValueError, TypeError):
        return None
    if node_type == "call_workflow":
        version_spec = data.get("version", "latest")
    else:  # loop
        version_spec = data.get("workflow_version", "latest")
    return sub_wf_id, version_spec


async def _collect_inherited_var_decls(
    db: AsyncSession,
    definition: dict[str, Any] | None,
    *,
    parent_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Coleta declaracoes de variaveis herdadas de sub-workflows referenciados.

    Percorre nos que invocam sub-workflows (``call_workflow`` e ``loop``),
    carrega a ``WorkflowVersion`` alvo (numero fixo ou mais recente publicada)
    e devolve as variaveis referenciadas pelo sub-workflow. Colisoes com nomes
    do pai sao descartadas porque o pai ja cuida do valor via auto-forward.
    Devolve tambem o conjunto de nomes coletados — util para estender
    ``referenced_names`` durante a resolucao.
    """
    if not definition:
        return [], set()
    from sqlalchemy import select as sa_select  # noqa: WPS433
    from app.models.workflow import WorkflowVersion  # noqa: WPS433

    parent_names = parent_names or set()
    collected_decls: list[dict[str, Any]] = []
    collected_names: set[str] = set()

    seen_versions: dict[tuple[UUID, Any], WorkflowVersion | None] = {}

    for node in definition.get("nodes") or []:
        ref = _extract_subworkflow_ref(node)
        if ref is None:
            continue
        sub_wf_id, version_spec = ref

        cache_key = (sub_wf_id, version_spec)
        if cache_key in seen_versions:
            version_row = seen_versions[cache_key]
        else:
            if version_spec == "latest" or version_spec is None:
                stmt = (
                    sa_select(WorkflowVersion)
                    .where(
                        WorkflowVersion.workflow_id == sub_wf_id,
                        WorkflowVersion.published.is_(True),
                    )
                    .order_by(WorkflowVersion.version.desc())
                    .limit(1)
                )
            else:
                try:
                    version_num = int(version_spec)
                except (TypeError, ValueError):
                    seen_versions[cache_key] = None
                    continue
                stmt = sa_select(WorkflowVersion).where(
                    WorkflowVersion.workflow_id == sub_wf_id,
                    WorkflowVersion.version == version_num,
                )
            version_row = (await db.execute(stmt)).scalar_one_or_none()
            seen_versions[cache_key] = version_row

        if version_row is None:
            continue

        sub_def = version_row.definition if isinstance(version_row.definition, dict) else {}
        sub_raw_vars = sub_def.get("variables") or []
        sub_referenced = _collect_referenced_var_names(sub_def)

        for raw in sub_raw_vars:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name:
                continue
            if name not in sub_referenced:
                continue
            if name in parent_names or name in collected_names:
                continue
            collected_decls.append(raw)
            collected_names.add(name)

    return collected_decls, collected_names


async def _validate_and_resolve_variables(
    var_decls: list[dict[str, Any]],
    variable_values: dict[str, Any],
    referenced_names: set[str] | None = None,
) -> dict[str, Any]:
    """Valida e resolve os valores das variaveis declaradas no workflow.

    - Variaveis nao referenciadas por nos ativos sao puladas (mesmo criterio
      do schema endpoint — evita exigir valor de declaracoes "orfas").
    - required=True sem valor → ValueError com mensagem clara
    - Aplica default quando o valor esta ausente e required=False
    - Coerce o valor para o tipo declarado
    Retorna dict {nome: valor_resolvido}.
    """
    from app.schemas.workflow import WorkflowParam

    resolved: dict[str, Any] = {}
    for raw_decl in var_decls:
        try:
            decl = WorkflowParam.model_validate(raw_decl)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workflow.variable.malformed",
                variable_name=raw_decl.get("name", "<sem-nome>"),
                error=str(exc),
            )
            continue

        if referenced_names is not None and decl.name not in referenced_names:
            continue

        value = variable_values.get(decl.name)
        if value is None:
            if decl.required:
                raise ValueError(f"Variavel '{decl.name}' e obrigatoria.")
            value = decl.default
        else:
            value = _coerce_variable_value(decl.name, decl.type, value)

        resolved[decl.name] = value

    return resolved


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
        retry_from_execution_id: UUID | None = None,
        run_mode: str = "full",
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

        # --- Limite de concorrencia ---
        # Adquire slot apos saber o project_id — levanta ConcurrencyLimitError
        # se nenhum slot liberar dentro de SHIFT_EXECUTION_QUEUE_TIMEOUT segundos.
        project_id_str = str(workflow.project_id) if workflow.project_id else None
        await acquire_execution_slot(project_id_str)

        # Slot adquirido. Deve ser liberado em TODOS os caminhos de saida.
        # Para wait=False o slot e transferido para a background task.
        _release_slot_here = True
        try:
            # --- Resolucao de variaveis do workflow ---
            var_decls: list[dict[str, Any]] = workflow.definition.get("variables", [])
            variable_values_raw: dict[str, Any] = {}
            if isinstance(input_data, dict):
                variable_values_raw = input_data.get("variable_values") or {}

            referenced_names = _collect_referenced_var_names(workflow.definition)

            # Agrega variaveis herdadas de sub-workflows (nos call_workflow).
            # O valor submetido pelo usuario no formulario de execucao fica em
            # ``variable_values_raw`` junto com as do pai; a resolucao trata
            # ambos igualmente. Ja no runtime, quem entra no contexto via
            # ``context['vars']`` serve de fonte para o auto-forward do
            # ``CallWorkflowProcessor`` em cada sub-chamada.
            parent_names = {
                d.get("name") for d in var_decls if isinstance(d, dict) and d.get("name")
            }
            inherited_decls, inherited_names = await _collect_inherited_var_decls(
                db, workflow.definition, parent_names=parent_names
            )
            full_var_decls = list(var_decls) + list(inherited_decls)
            full_referenced = referenced_names | inherited_names

            resolved_vars = await _validate_and_resolve_variables(
                var_decls=full_var_decls,
                variable_values=variable_values_raw,
                referenced_names=full_referenced,
            )

            # Substitui {{vars.X}} na definicao antes de resolver conexoes e de
            # passar para o runner — garante que connection_id com template se
            # torna UUID real para _inject_connection_string.
            definition_for_exec = _substitute_vars_in_definition(
                workflow.definition, resolved_vars
            )

            resolved_connections = await connection_service.resolve_for_workflow(
                db,
                definition_for_exec,
                project_id=workflow.project_id,
                workspace_id=workspace_id,
            )

            effective_mode = mode or (
                "production" if workflow.status == "published" else "test"
            )

            # Mascara segredos antes de persistir em input_data (secrets nao ficam em claro no DB)
            secret_names = {
                d.get("name") for d in var_decls if isinstance(d, dict) and d.get("type") == "secret"
            }
            masked_vars: dict[str, Any] = {
                k: "***" if k in secret_names else v for k, v in resolved_vars.items()
            }

            _snapshot_hash = hashlib.sha256(
                json.dumps(definition_for_exec, sort_keys=True, default=str).encode()
            ).hexdigest()

            execution = WorkflowExecution(
                workflow_id=workflow.id,
                status="RUNNING",
                triggered_by=triggered_by,
                started_at=datetime.now(timezone.utc),
                input_data={"variable_values": masked_vars} if masked_vars else None,
                workflow_definition_snapshot=definition_for_exec,
                definition_snapshot_hash=_snapshot_hash,
            )
            db.add(execution)
            await db.flush()

            # Captura dados antes de liberar a sessao — a execucao roda em background
            # (ou inline) e abre sua propria sessao para persistir o resultado.
            execution_id = execution.id
            exec_status = execution.status
            await db.commit()

            # Lê timeout da definicao do workflow; None usa o default de config.
            raw_timeout = definition_for_exec.get("max_execution_time_seconds")
            wf_timeout = int(raw_timeout) if raw_timeout is not None else None

            run_coro = self._run_and_persist(
                execution_id=execution_id,
                workflow_id=workflow.id,
                workflow_definition=definition_for_exec,
                triggered_by=triggered_by,
                input_data=input_data or {},
                resolved_connections=resolved_connections,
                variable_values=resolved_vars,
                event_sink=event_sink,
                mode=effective_mode,
                target_node_id=target_node_id,
                max_execution_time_seconds=wf_timeout,
                retry_from_execution_id=retry_from_execution_id,
                run_mode=run_mode,
            )

            if wait:
                # Roda inline — quem chamou (SSE) ja esta consumindo eventos
                # em paralelo via event_sink/queue.
                await run_coro
            else:
                _p = project_id_str

                async def _bg_run_with_slot_release() -> None:
                    try:
                        await run_coro
                    finally:
                        release_execution_slot(_p)

                task = asyncio.create_task(
                    _bg_run_with_slot_release(),
                    name=f"workflow-execution-{execution_id}",
                )
                await execution_registry.register(execution_id, task)
                _release_slot_here = False  # background task e responsavel

            return ExecutionResponse(
                execution_id=execution_id,
                status=exec_status,
            )
        finally:
            if _release_slot_here:
                release_execution_slot(project_id_str)

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
        retry_from_execution_id: UUID | None = None,
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
            retry_from_execution_id=retry_from_execution_id,
        )

    async def execute_workflow(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        input_data: dict[str, Any] | None = None,
        retry_from_execution_id: UUID | None = None,
        run_mode: str = "full",
    ) -> ExecutionResponse:
        """Mantem compatibilidade com a rota POST /execute (HTTP publica)."""
        return await self.run(
            db=db,
            workflow_id=workflow_id,
            triggered_by="api",
            input_data=input_data,
            mode="production",
            retry_from_execution_id=retry_from_execution_id,
            run_mode=run_mode,
        )

    async def validate_workflow(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        input_data: dict[str, Any] | None = None,
    ) -> "ValidateExecutionResponse":
        """Valida variaveis e testa conectividade das conexoes referenciadas
        pelo workflow, sem invocar o runner nem criar uma ``WorkflowExecution``.

        Esse caminho e usado pelo ``run_mode=validate`` — equivalente a um
        "dry run sem dados": garante que o workflow esta apto a executar
        (variaveis obrigatorias presentes, conectores respondem) sem o custo
        de processar o pipeline.
        """
        from app.schemas.workflow import (
            ValidateConnectionResult,
            ValidateExecutionResponse,
        )

        errors: list[str] = []
        missing_vars: list[str] = []
        connection_results: list[ValidateConnectionResult] = []

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
            return ValidateExecutionResponse(
                ok=False, errors=[f"Workflow '{workflow_id}' nao encontrado."]
            )

        workflow = row[0]
        workspace_id = row[1]

        var_decls: list[dict[str, Any]] = workflow.definition.get("variables", [])
        variable_values_raw: dict[str, Any] = {}
        if isinstance(input_data, dict):
            variable_values_raw = input_data.get("variable_values") or {}

        referenced_names = _collect_referenced_var_names(workflow.definition)
        parent_names = {
            d.get("name") for d in var_decls if isinstance(d, dict) and d.get("name")
        }
        try:
            inherited_decls, inherited_names = await _collect_inherited_var_decls(
                db, workflow.definition, parent_names=parent_names
            )
        except Exception as exc:  # noqa: BLE001
            return ValidateExecutionResponse(
                ok=False, errors=[f"Falha ao resolver sub-workflows: {exc}"]
            )

        full_var_decls = list(var_decls) + list(inherited_decls)
        full_referenced = referenced_names | inherited_names

        try:
            resolved_vars = await _validate_and_resolve_variables(
                var_decls=full_var_decls,
                variable_values=variable_values_raw,
                referenced_names=full_referenced,
            )
        except ValueError as exc:
            # ``_validate_and_resolve_variables`` levanta ValueError com a
            # lista de variaveis faltantes — repassamos como errors para que
            # o consumidor possa exibir ao usuario.
            msg = str(exc)
            if "faltando" in msg.lower() or "obrigat" in msg.lower():
                missing_vars = [msg]
            else:
                errors.append(msg)
            return ValidateExecutionResponse(
                ok=False, missing_variables=missing_vars, errors=errors
            )

        # Substitui {{vars.X}} para permitir que resolve_for_workflow ache
        # os connection_ids reais.
        definition_for_exec = _substitute_vars_in_definition(
            workflow.definition, resolved_vars
        )
        try:
            resolved_connections = await connection_service.resolve_for_workflow(
                db,
                definition_for_exec,
                project_id=workflow.project_id,
                workspace_id=workspace_id,
            )
        except Exception as exc:  # noqa: BLE001
            return ValidateExecutionResponse(
                ok=False, errors=[f"Falha ao resolver conexoes: {exc}"]
            )

        for conn_id_str in (resolved_connections or {}).keys():
            try:
                conn_uuid = UUID(conn_id_str)
            except ValueError:
                errors.append(f"ID de conexao invalido no grafo: {conn_id_str}")
                continue
            conn_obj = await connection_service.get(db, conn_uuid)
            conn_name = conn_obj.name if conn_obj is not None else str(conn_uuid)
            try:
                test_result = await connection_service.test_connection(db, conn_uuid)
                connection_results.append(
                    ValidateConnectionResult(
                        connection_id=conn_uuid,
                        name=conn_name,
                        ok=bool(test_result.success),
                        error=None if test_result.success else test_result.message,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                connection_results.append(
                    ValidateConnectionResult(
                        connection_id=conn_uuid,
                        name=conn_name,
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        all_connections_ok = all(c.ok for c in connection_results)
        ok = all_connections_ok and not errors and not missing_vars
        return ValidateExecutionResponse(
            ok=ok,
            connections=connection_results,
            missing_variables=missing_vars,
            errors=errors,
        )

    async def _run_and_persist(
        self,
        execution_id: UUID,
        workflow_id: UUID,
        workflow_definition: dict[str, Any],
        triggered_by: str,
        input_data: dict[str, Any],
        resolved_connections: dict[str, str] | None,
        variable_values: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
        mode: str = "production",
        target_node_id: str | None = None,
        max_execution_time_seconds: int | None = None,
        retry_from_execution_id: UUID | None = None,
        run_mode: str = "full",
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

        # Timeout efetivo: usa o campo do workflow, cai para o default de config.
        # Valor 0 significa sem limite.
        effective_timeout = (
            max_execution_time_seconds
            if max_execution_time_seconds is not None
            else settings.WORKFLOW_DEFAULT_MAX_EXECUTION_TIME_SECONDS
        )

        # Buffer de log estruturado: persiste eventos do runner em
        # ``workflow_execution_logs`` para troubleshooting remoto via API.
        # O wrapper envolve o ``event_sink`` original (SSE, se houver) sem
        # alterar seu comportamento.
        log_buffer = ExecutionLogBuffer(execution_id)
        wrapped_sink = log_buffer.event_sink_wrapper(event_sink)

        with bind_context(execution_id=str(execution_id), workflow_id=str(workflow_id)):
            try:
                # Carrega checkpoints da execucao anterior (se for um retry).
                checkpoint_results: dict | None = None
                if retry_from_execution_id is not None:
                    checkpoint_results = await checkpoint_service.load_checkpoints(retry_from_execution_id)
                    if checkpoint_results:
                        logger.info(
                            "execution.checkpoints_loaded",
                            source_execution_id=str(retry_from_execution_id),
                            checkpointed_nodes=list(checkpoint_results.keys()),
                        )
                        await checkpoint_service.mark_checkpoints_used(
                            retry_from_execution_id, execution_id
                        )
                        await log_buffer.record(
                            level="info",
                            message=(
                                f"Retomando execucao a partir de {retry_from_execution_id}. "
                                f"Nos com checkpoint: {', '.join(checkpoint_results.keys())}"
                            ),
                            context={"checkpointed_nodes": list(checkpoint_results.keys())},
                        )

                run_coro = run_workflow(
                    workflow_payload=workflow_definition,
                    workflow_id=str(workflow_id),
                    triggered_by=triggered_by,
                    input_data=input_data,
                    execution_id=str(execution_id),
                    resolved_connections=resolved_connections,
                    variable_values=variable_values,
                    event_sink=wrapped_sink,
                    mode=mode,
                    target_node_id=target_node_id,
                    checkpoint_results=checkpoint_results,
                    run_mode=run_mode,
                    preview_max_rows=(
                        settings.WORKFLOW_PREVIEW_MAX_ROWS
                        if run_mode == "preview"
                        else None
                    ),
                )
                if effective_timeout and effective_timeout > 0:
                    result = await asyncio.wait_for(run_coro, timeout=float(effective_timeout))
                else:
                    result = await run_coro
            except asyncio.TimeoutError:
                cancelled = True
                error = (
                    f"Execucao cancelada por timeout ({effective_timeout}s)."
                )
                logger.warning(
                    "execution.timeout",
                    timeout_seconds=effective_timeout,
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
                # Fecha o buffer de log antes de persistir o estado final
                # para garantir que qualquer evento de fim (execution_end,
                # cancelled) ja esteja gravado em workflow_execution_logs.
                await log_buffer.close()
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
