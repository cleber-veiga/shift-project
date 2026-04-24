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
import datetime as _dt
import decimal as _decimal
import re as _re
from typing import Any
from uuid import UUID, uuid4

import duckdb
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.data_pipelines.duckdb_storage import (
    build_table_ref,
    find_duckdb_reference,
)
from app.db.session import async_session_factory
from app.models.workflow import Workflow, WorkflowVersion
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError

_logger = get_logger(__name__)

# Cap de seguranca ao rehydratar um upstream DuckDB pra dentro do
# ``context`` antes de resolver os templates de ``input_mapping``. Para
# iterar sobre datasets grandes use ``loop`` (For Each), nao call_workflow.
_SUBWORKFLOW_REHYDRATE_ROW_CAP = 1000

# Captura referencias a ``upstream_results.<nodeId>.rows`` em qualquer
# lugar dentro de uma string de template (aceita chaves simples, {{…}}
# ou ``{…}``). Usado pra decidir QUAIS upstreams precisam ser carregados.
_UPSTREAM_ROWS_REF_RE = _re.compile(
    r"upstream_results\.([A-Za-z0-9_\-]+)\.rows\b",
)


def _serialize_duckdb_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, _decimal.Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return value


def _load_duckdb_rows(
    database_path: str,
    table_name: str,
    dataset_name: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Le ate ``limit`` linhas de uma tabela DuckDB e devolve dicts."""
    conn = duckdb.connect(database_path, read_only=True)
    try:
        table_ref = build_table_ref(
            {
                "storage_type": "duckdb",
                "database_path": database_path,
                "table_name": table_name,
                "dataset_name": dataset_name,
            }
        )
        cursor = conn.execute(f"SELECT * FROM {table_ref} LIMIT {int(limit)}")
        columns = [desc[0] for desc in cursor.description or []]
        raw_rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        {col: _serialize_duckdb_value(val) for col, val in zip(columns, row)}
        for row in raw_rows
    ]


def _referenced_upstream_ids(input_mapping: dict[str, Any]) -> set[str]:
    """Coleta os ``nodeId`` de upstreams citados via ``.rows`` no mapping."""
    ids: set[str] = set()
    for raw_expr in input_mapping.values():
        if isinstance(raw_expr, str):
            for match in _UPSTREAM_ROWS_REF_RE.finditer(raw_expr):
                ids.add(match.group(1))
    return ids


def _rehydrate_upstream_rows(
    context: dict[str, Any],
    input_mapping: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    """Devolve um contexto local com ``rows`` preenchido pros upstreams.

    Nos materializados em DuckDB (mapper/filter/dedup/aggregator) guardam
    as linhas em disco e publicam no ``upstream_results`` apenas um ref
    ``{storage_type: duckdb, database_path, table_name}``. Templates como
    ``{{upstream_results.<id>.rows.0.campo}}`` nao resolvem contra isso.

    Esta funcao detecta quais upstreams sao citados via ``.rows`` no
    ``input_mapping``, carrega ate ``_SUBWORKFLOW_REHYDRATE_ROW_CAP`` linhas
    de cada um e injeta a chave ``rows`` num clone raso do upstream —
    suficiente pro resolver de templates. O contexto original fica intacto.
    """
    upstream_results = context.get("upstream_results")
    if not isinstance(upstream_results, dict):
        return context

    referenced = _referenced_upstream_ids(input_mapping)
    if not referenced:
        return context

    patched_upstream: dict[str, Any] = dict(upstream_results)
    changed = False
    for upstream_id in referenced:
        entry = patched_upstream.get(upstream_id)
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("rows"), list):
            continue  # ja tem rows inline — nao precisa rehydratar
        ref = find_duckdb_reference(entry)
        if ref is None:
            continue
        try:
            rows = _load_duckdb_rows(
                database_path=str(ref["database_path"]),
                table_name=str(ref["table_name"]),
                dataset_name=ref.get("dataset_name"),
                limit=_SUBWORKFLOW_REHYDRATE_ROW_CAP,
            )
        except duckdb.Error as exc:
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': falha ao carregar linhas do "
                f"upstream '{upstream_id}' para resolver input_mapping — {exc}."
            ) from exc
        patched_entry = dict(entry)
        patched_entry["rows"] = rows
        patched_upstream[upstream_id] = patched_entry
        changed = True
        _logger.info(
            "call_workflow.rehydrate_rows",
            node_id=node_id,
            upstream_id=upstream_id,
            rows_loaded=len(rows),
            capped=len(rows) >= _SUBWORKFLOW_REHYDRATE_ROW_CAP,
        )

    if not changed:
        return context
    patched = dict(context)
    patched["upstream_results"] = patched_upstream
    return patched


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

    O processor roda em thread via ``asyncio.to_thread``. A coroutine
    async que invoca o sub-workflow e despachada de volta ao event loop
    principal do runner (``context['_main_loop']``) via
    ``asyncio.run_coroutine_threadsafe``, porque recursos async globais
    (engine SQLAlchemy/asyncpg, etc.) estao ligados aquele loop.
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
        variable_values_raw = config.get("variable_values") or {}
        if not isinstance(variable_values_raw, dict):
            raise NodeProcessingError(
                f"No call_workflow '{node_id}': variable_values deve ser um dict."
            )

        # Auto-forward: variaveis do pai sao propagadas automaticamente para
        # o sub-workflow quando os nomes batem. Assim o usuario nao precisa
        # mapear manualmente (ex.: ``ConstrushowDb`` no pai -> ``ConstrushowDb``
        # no sub). ``variable_values_raw`` do config ainda tem precedencia.
        parent_vars = context.get("vars")
        if not isinstance(parent_vars, dict):
            parent_vars = {}

        # Rehydratacao sob demanda: se algum template referencia
        # ``upstream_results.<id>.rows`` e esse upstream publicou apenas
        # um ref DuckDB, carrega as linhas pra dentro de um contexto
        # local antes de resolver. Evita "None" silencioso vira erro de
        # "input obrigatorio nao foi fornecido".
        resolve_context = _rehydrate_upstream_rows(
            context, input_mapping_raw, node_id
        )

        # Resolve mapeamento de inputs contra o contexto (ja rehydratado).
        mapped_inputs: dict[str, Any] = {}
        for name, raw_expr in input_mapping_raw.items():
            if isinstance(raw_expr, str):
                mapped_inputs[name] = self.resolve_template(
                    raw_expr, resolve_context
                )
            else:
                mapped_inputs[name] = raw_expr

        # Resolve variable_values do sub-workflow. Templates do caller
        # (ex: ``{{vars.X}}`` referenciando variaveis do workflow pai ja
        # substituidas em definition_for_exec) entram como strings literais
        # apos substituicao. Aqui tambem resolvemos placeholders dinamicos
        # ``{{upstream_results.*}}`` contra o contexto atual.
        mapped_vars: dict[str, Any] = {}
        for name, raw_expr in variable_values_raw.items():
            if isinstance(raw_expr, str):
                mapped_vars[name] = self.resolve_template(
                    raw_expr, resolve_context
                )
            else:
                mapped_vars[name] = raw_expr

        call_stack = list(context.get("call_stack") or [])

        coro = _invoke_subworkflow(
            node_id=node_id,
            target_workflow_id=target_workflow_id,
            version_spec=version_spec,
            mapped_inputs=mapped_inputs,
            variable_values=mapped_vars,
            parent_vars=dict(parent_vars),
            call_stack=call_stack,
            timeout_seconds=timeout_seconds,
        )

        main_loop = context.get("_main_loop")
        if isinstance(main_loop, asyncio.AbstractEventLoop) and main_loop.is_running():
            # Dispatch para o loop principal do runner — recursos async
            # globais (engine/asyncpg) estao ligados a ele. Adicionamos
            # margem ao ``timeout`` do futures.result() porque o timeout
            # "duro" ja e aplicado dentro de ``_invoke_subworkflow``.
            future = asyncio.run_coroutine_threadsafe(coro, main_loop)
            result = future.result(timeout=timeout_seconds + 30)
        else:
            # Fallback (testes unit ou ambiente sem loop rodando): cria
            # um loop local. Pode falhar se o engine global ja estiver
            # ligado a outro loop.
            result = asyncio.run(coro)

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
    variable_values: dict[str, Any] | None = None,
    parent_vars: dict[str, Any] | None = None,
    in_loop: bool = False,
) -> dict[str, Any]:
    """Coreografia async: carrega versao, valida inputs, roda sub-workflow."""
    # Import lazy para evitar ciclo.
    from app.services.workflow_service import (  # noqa: WPS433
        _substitute_vars_in_definition,
        _validate_and_resolve_variables,
        _collect_referenced_var_names,
    )

    version = await _load_version(target_workflow_id, version_spec, node_id)
    _validate_inputs(node_id, version, mapped_inputs)

    # Resolve variaveis globais do sub-workflow antes de qualquer coisa —
    # garante que ``{{vars.X}}`` dentro da definition vire valor concreto
    # (inclusive em connection_id, que a resolucao de conexao abaixo
    # consulta literalmente).
    sub_var_decls: list[dict[str, Any]] = (
        version.definition.get("variables", []) if isinstance(version.definition, dict) else []
    )
    sub_referenced = _collect_referenced_var_names(version.definition)

    # Merge: auto-forward do pai -> override via variable_values do config.
    # Exemplo: pai resolveu ``ConstrushowDb = <uuid>``; sub tambem declara
    # ``ConstrushowDb``. Sem config explicito, o UUID flui direto. Se o
    # usuario tiver mapeado ``variable_values`` no no, esse valor vence.
    merged_values: dict[str, Any] = {}
    if parent_vars:
        for decl in sub_var_decls:
            if not isinstance(decl, dict):
                continue
            name = decl.get("name")
            if isinstance(name, str) and name in parent_vars:
                merged_values[name] = parent_vars[name]
    if variable_values:
        for k, v in variable_values.items():
            # Trata "" como "nao fornecido" — evita que um placeholder do UI
            # apague o auto-forward do pai.
            if v is None or (isinstance(v, str) and v.strip() == ""):
                continue
            merged_values[k] = v

    try:
        resolved_sub_vars = await _validate_and_resolve_variables(
            var_decls=sub_var_decls,
            variable_values=merged_values,
            referenced_names=sub_referenced,
        )
    except ValueError as exc:
        # Propaga como erro de node — o usuario ve mensagem contextualizada.
        raise NodeProcessingError(
            f"No call_workflow '{node_id}': {exc}"
        ) from exc

    definition_for_exec = _substitute_vars_in_definition(
        version.definition, resolved_sub_vars
    )

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
            definition_for_exec,
            project_id=project_id,
            workspace_id=workspace_id,
        )

    # execution_id UNICO por invocacao — garante isolamento de arquivos
    # DuckDB por iteracao. Sem isso, loops paralelos colidem no mesmo
    # diretorio ``executions/<id>/<node_id>.duckdb`` (erro "file being
    # used by another process" no Windows e "write-write conflict" no
    # catalog do DuckDB).
    sub_execution_id = f"sub-{uuid4()}"
    try:
        sub_result = await asyncio.wait_for(
            run_workflow(
                workflow_payload=definition_for_exec,
                workflow_id=str(target_workflow_id),
                triggered_by="subworkflow",
                input_data=mapped_inputs,
                execution_id=sub_execution_id,
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
