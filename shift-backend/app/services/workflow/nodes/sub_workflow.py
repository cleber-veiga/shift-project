"""
Processadores para sub-workflows (Fase 3).

Tres nos trabalham em conjunto para permitir que um workflow invoque
outro workflow publicado como sub-rotina:

- ``workflow_input``  : ponto de entrada interno do sub-workflow. Expoe
                        ``context['input_data']`` como saida padrao para
                        que os nos a jusante consumam os parametros
                        declarados no ``input_schema``.
- ``workflow_output`` : ponto de saida interno. Acumula valores em
                        ``context['workflow_output']`` (dict mutavel
                        compartilhado com o runner) para compor o
                        pacote de resultado retornado ao caller.
- ``call_workflow``   : invoca uma ``WorkflowVersion`` publicada em
                        isolamento (contexto novo, sem ver upstream
                        do pai), mapeando ``input_mapping`` para
                        ``input_data`` e publicando ``workflow_output``
                        no campo configurado.

Isolamento
----------
O ``run_workflow`` aninhado nao herda ``upstream_results`` nem
conexoes resolvidas do pai. Ele carrega suas proprias connections
via workflow_service (resolucao pre-execucao). A comunicacao e
estritamente via inputs -> outputs declarados.

Ciclos e profundidade sao tratados pelo proprio ``run_workflow``
via ``call_stack`` + ``max_depth``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.workflow import Workflow, WorkflowVersion
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("workflow_input")
class WorkflowInputProcessor(BaseNodeProcessor):
    """Exibe ``input_data`` no contexto como saida do no."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        input_data = context.get("input_data") or {}
        output_field = str(config.get("output_field") or "data")
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: input_data,
        }


@register_processor("workflow_output")
class WorkflowOutputProcessor(BaseNodeProcessor):
    """Captura campos do contexto e acumula no pacote de saida."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        mapping_raw = config.get("mapping") or {}
        if not isinstance(mapping_raw, dict):
            raise NodeProcessingError(
                f"No workflow_output '{node_id}': mapping deve ser um dict."
            )

        captured: dict[str, Any] = {}
        for name, raw_expr in mapping_raw.items():
            if not isinstance(raw_expr, str):
                captured[name] = raw_expr
                continue
            captured[name] = self.resolve_template(raw_expr, context)

        # ``workflow_output`` no contexto e o dict mutavel criado pelo
        # runner em execution_context. Atualizar in-place garante que o
        # caller (call_workflow) enxergue o pacote final.
        accumulator = context.get("workflow_output")
        if isinstance(accumulator, dict):
            accumulator.update(captured)

        return {
            "node_id": node_id,
            "status": "completed",
            "captured": captured,
        }


@register_processor("call_workflow")
class CallWorkflowProcessor(BaseNodeProcessor):
    """Invoca uma versao publicada de outro workflow como sub-rotina.

    Executa sincronamente dentro do thread do processor (``asyncio.run``
    cria um event loop novo — o processor ja roda em ``asyncio.to_thread``).
    """

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id_raw = config.get("workflow_id")
        if not workflow_id_raw:
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': workflow_id e obrigatorio."
            )
        try:
            target_workflow_id = UUID(str(workflow_id_raw))
        except (ValueError, TypeError) as exc:
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': workflow_id invalido."
            ) from exc

        version_spec = config.get("version", "latest")
        output_field = str(config.get("output_field") or "workflow_result")
        timeout_seconds = int(config.get("timeout_seconds") or 300)
        input_mapping_raw = config.get("input_mapping") or {}
        if not isinstance(input_mapping_raw, dict):
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': input_mapping deve ser um dict."
            )

        # Resolve mapeamento de inputs contra o contexto do pai.
        mapped_inputs: dict[str, Any] = {}
        for name, raw_expr in input_mapping_raw.items():
            if isinstance(raw_expr, str):
                mapped_inputs[name] = self.resolve_template(raw_expr, context)
            else:
                mapped_inputs[name] = raw_expr

        call_stack = list(context.get("call_stack") or [])

        # Carrega a versao + valida inputs + executa sub-workflow.
        result = asyncio.run(
            _invoke_subworkflow(
                node_id=node_id,
                target_workflow_id=target_workflow_id,
                version_spec=version_spec,
                mapped_inputs=mapped_inputs,
                call_stack=call_stack,
                timeout_seconds=timeout_seconds,
            )
        )

        return {
            "node_id": node_id,
            "status": "completed",
            "sub_workflow_id": str(target_workflow_id),
            "sub_version": result["version"],
            "output_field": output_field,
            output_field: result["workflow_output"],
        }


async def _invoke_subworkflow(
    *,
    node_id: str,
    target_workflow_id: UUID,
    version_spec: Any,
    mapped_inputs: dict[str, Any],
    call_stack: list[str],
    timeout_seconds: int,
    in_loop: bool = False,
) -> dict[str, Any]:
    """Coreografia async: carrega versao, valida inputs, roda sub-workflow."""
    version = await _load_version(target_workflow_id, version_spec, node_id)
    _validate_inputs(node_id, version, mapped_inputs)

    # Resolve connections do sub-workflow (seu proprio escopo — nao
    # herdamos nada do pai). Importamos aqui para evitar ciclo de import.
    from app.services.connection_service import connection_service  # noqa: WPS433
    from app.orchestration.flows.dynamic_runner import run_workflow

    async with async_session_factory() as session:  # type: AsyncSession
        wf_row = await session.execute(
            sa.select(Workflow.project_id, Workflow.workspace_id).where(
                Workflow.id == target_workflow_id
            )
        )
        scope = wf_row.first()
        if scope is None:
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': workflow {target_workflow_id} "
                "nao encontrado no banco."
            )
        project_id, workspace_id = scope
        resolved_connections = await connection_service.resolve_for_workflow(
            session,
            version.definition,
            project_id=project_id,
            workspace_id=workspace_id,
        )

    try:
        sub_result = await asyncio.wait_for(
            run_workflow(
                workflow_payload=version.definition,
                workflow_id=str(target_workflow_id),
                triggered_by="subworkflow",
                input_data=mapped_inputs,
                execution_id=None,
                resolved_connections=resolved_connections,
                mode="production",
                call_stack=call_stack,
                in_loop=in_loop,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise NodeProcessingError(
            f"No call_workflow '{node_id}': sub-workflow excedeu "
            f"{timeout_seconds}s."
        ) from exc

    status = sub_result.get("status")
    if status != "completed":
        raise NodeProcessingError(
            f"No call_workflow '{node_id}': sub-workflow retornou status "
            f"'{status}': {sub_result.get('error') or sub_result.get('reason') or ''}"
        )

    workflow_output = dict(sub_result.get("workflow_output") or {})
    _validate_outputs(node_id, version, workflow_output)

    return {
        "version": version.version,
        "workflow_output": workflow_output,
    }


async def _load_version(
    target_workflow_id: UUID,
    version_spec: Any,
    node_id: str,
) -> WorkflowVersion:
    """Carrega a ``WorkflowVersion`` alvo — numero fixo ou 'latest'."""
    async with async_session_factory() as session:  # type: AsyncSession
        if version_spec == "latest" or version_spec is None:
            stmt = (
                sa.select(WorkflowVersion)
                .where(
                    WorkflowVersion.workflow_id == target_workflow_id,
                    WorkflowVersion.published.is_(True),
                )
                .order_by(WorkflowVersion.version.desc())
                .limit(1)
            )
        else:
            try:
                version_num = int(version_spec)
            except (TypeError, ValueError) as exc:
                raise NodeProcessingError(
                    f"No call_workflow '{node_id}': version '{version_spec}' invalida."
                ) from exc
            stmt = sa.select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == target_workflow_id,
                WorkflowVersion.version == version_num,
            )

        result = await session.execute(stmt)
        version = result.scalar_one_or_none()

    if version is None:
        raise NodeProcessingError(
            f"No call_workflow '{node_id}': versao {version_spec} do "
            f"workflow {target_workflow_id} nao encontrada."
        )
    return version


def _validate_inputs(
    node_id: str,
    version: WorkflowVersion,
    mapped_inputs: dict[str, Any],
) -> None:
    """Exige campos required e rejeita inputs nao declarados."""
    declared = version.input_schema or []
    declared_names = {str(p.get("name")) for p in declared if isinstance(p, dict)}

    for param in declared:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name"))
        required = bool(param.get("required", True))
        has_value = name in mapped_inputs and mapped_inputs[name] is not None
        if required and not has_value:
            default = param.get("default")
            if default is None:
                raise NodeProcessingError(
                    f"No call_workflow '{node_id}': input obrigatorio '{name}' "
                    "nao foi fornecido."
                )
            mapped_inputs[name] = default

    extras = set(mapped_inputs) - declared_names
    if extras:
        raise NodeProcessingError(
            f"No call_workflow '{node_id}': inputs nao declarados no "
            f"io_schema: {sorted(extras)}."
        )


def _validate_outputs(
    node_id: str,
    version: WorkflowVersion,
    workflow_output: dict[str, Any],
) -> None:
    """Checa se todos os outputs required foram emitidos pelo sub-workflow."""
    declared = version.output_schema or []
    for param in declared:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name"))
        required = bool(param.get("required", True))
        if required and name not in workflow_output:
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': sub-workflow nao produziu "
                f"o output obrigatorio '{name}'."
            )
