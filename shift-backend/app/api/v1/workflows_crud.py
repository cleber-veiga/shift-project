"""
Endpoints CRUD de Workflows e Templates.

Rotas de execucao permanecem em workflows.py.
"""

import re
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_VAR_REF_RE = re.compile(r"\{\{\s*vars\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _collect_referenced_vars(definition: dict[str, Any] | None) -> set[str]:
    """Retorna nomes de variaveis referenciadas via {{vars.X}} nos nos ativos.

    Nos com ``data.enabled == False`` sao ignorados, assim como refs dentro
    de ``data.pinnedOutput`` (saida congelada, nao executa).
    """
    if not definition:
        return set()
    found: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            for m in _VAR_REF_RE.finditer(obj):
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
        # Ignora o pinnedOutput — e resultado de execucao anterior, nao config.
        scrubbed = {k: v for k, v in data.items() if k != "pinnedOutput"} if isinstance(data, dict) else data
        _walk(scrubbed)
    return found

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.security import authorization_service, require_permission
from app.models import Project, User
from app.models.workflow import Workflow, WorkflowVersion
from app.schemas.workflow import (
    ConnectionOptionResponse,
    InheritedVariable,
    VariablesSchemaResponse,
    WorkflowCloneRequest,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowParam,
    WorkflowResponse,
    WorkflowUpdate,
    WorkflowVariablesSchema,
)
from app.services.scheduler_service import (
    get_schedule_status,
    register_workflow_schedule,
    remove_workflow_schedule,
)
from app.services.workflow_crud_service import workflow_crud_service
from app.services.workflow_file_upload_service import workflow_file_upload_service

router = APIRouter(tags=["workflows"])


# ---------------------------------------------------------------------------
# Criacao
# ---------------------------------------------------------------------------

@router.post(
    "/workflows",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> WorkflowResponse:
    """Cria um workflow ou template.

    - Workflows de workspace: fornecer `workspace_id`.
    - Workflows de projeto: fornecer `project_id`.
    - Templates: fornecer `workspace_id`, `is_template=true`.
    """
    try:
        workflow = await workflow_crud_service.create(db, payload)
        await db.commit()
        return WorkflowResponse.model_validate(workflow)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/workflows",
    response_model=WorkflowListResponse,
)
async def list_project_workflows(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _=Depends(require_permission("project", "CLIENT")),
) -> WorkflowListResponse:
    """Lista os workflows de um projeto."""
    items, total = await workflow_crud_service.list_for_project_paginated(
        db, project_id, page=page, size=size
    )
    return WorkflowListResponse(
        items=[WorkflowResponse.model_validate(w) for w in items],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/workspaces/{workspace_id}/workflows",
    response_model=WorkflowListResponse,
)
async def list_workspace_workflows(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> WorkflowListResponse:
    """Lista todos os workflows de um workspace (inclui templates e workflows normais)."""
    items, total = await workflow_crud_service.list_for_workspace_paginated(
        db, workspace_id, page=page, size=size
    )
    return WorkflowListResponse(
        items=[WorkflowResponse.model_validate(w) for w in items],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/workspaces/{workspace_id}/templates",
    response_model=WorkflowListResponse,
)
async def list_workspace_templates(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> WorkflowListResponse:
    """Lista os templates publicados de um workspace."""
    items, total = await workflow_crud_service.list_templates_for_workspace_paginated(
        db, workspace_id, page=page, size=size
    )
    return WorkflowListResponse(
        items=[WorkflowResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Leitura, atualizacao e remocao
# ---------------------------------------------------------------------------

@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowResponse,
)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> WorkflowResponse:
    """Retorna detalhes e a definicao JSON de um workflow."""
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )
    return WorkflowResponse.model_validate(workflow)


@router.get(
    "/workflows/{workflow_id}/definition/events",
    response_class=StreamingResponse,
)
async def stream_definition_events(
    workflow_id: UUID,
    since: Optional[int] = Query(None, description="Replay eventos com seq > since"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream SSE de mudancas na definicao de um workflow.

    Conectar com EventSource('/api/v1/workflows/{id}/definition/events').
    Fornecer ?since=<seq> para replay de eventos perdidos ao reconectar.
    """
    # Explicit scope check — always 404 (never 403) to avoid leaking resource existence
    result = await db.execute(
        select(func.coalesce(Workflow.workspace_id, Project.workspace_id))
        .select_from(Workflow)
        .outerjoin(Project, Project.id == Workflow.project_id)
        .where(Workflow.id == workflow_id)
    )
    effective_ws_id = result.scalar_one_or_none()
    if effective_ws_id is None or not await authorization_service.has_permission(
        db=db,
        user_id=current_user.id,
        scope="workspace",
        required_role="VIEWER",
        scope_id=effective_ws_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow nao encontrado.",
        )

    from app.services.definition_event_service import definition_event_service

    return StreamingResponse(
        definition_event_service.sse_stream(workflow_id=workflow_id, since_seq=since),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.put(
    "/workflows/{workflow_id}",
    response_model=WorkflowResponse,
)
async def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> WorkflowResponse:
    """Atualiza metadados ou a definicao JSON de um workflow.

    Apos salvar, sincroniza o agendamento no scheduler interno seguindo a regra:
      - status=published + definition contem no cron -> cria/atualiza schedule
      - caso contrario -> remove schedule (idempotente)
    """
    try:
        workflow = await workflow_crud_service.update(db, workflow_id, payload)
        await db.commit()
        register_workflow_schedule(workflow)
        return WorkflowResponse.model_validate(workflow)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "MANAGER")),
) -> None:
    """Remove um workflow.

    Tambem remove qualquer job cron associado no scheduler interno.
    """
    try:
        await workflow_crud_service.delete(db, workflow_id)
        await db.commit()
        remove_workflow_schedule(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Acoes especiais
# ---------------------------------------------------------------------------

@router.post(
    "/workflows/{workflow_id}/publish",
    response_model=WorkflowResponse,
)
async def publish_template(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> WorkflowResponse:
    """Publica um template, tornando-o visivel para clonagem.

    Requer role CONSULTANT no workspace ao qual o template pertence.
    """
    try:
        workflow = await workflow_crud_service.publish(db, workflow_id)
        await db.commit()
        return WorkflowResponse.model_validate(workflow)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get(
    "/workflows/{workflow_id}/schedule",
)
async def get_workflow_schedule(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> dict:
    """Retorna o estado de agendamento cron do workflow.

    O schedule esta ATIVO quando:
      - workflow.status == 'published'
      - definition contem um no cron com cron_expression
    """
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    return get_schedule_status(workflow)


@router.post(
    "/workflows/{workflow_id}/clone",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_template(
    workflow_id: UUID,
    clone_request: WorkflowCloneRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "EDITOR")),
) -> WorkflowResponse:
    """Clona um template publicado para um projeto destino.

    O campo `connection_mapping` permite substituir os `connection_id` do
    template pelos IDs equivalentes no ambiente do projeto destino:
    `{"uuid_original": "uuid_novo"}`.
    """
    try:
        cloned = await workflow_crud_service.clone_template(db, workflow_id, clone_request)
        await db.commit()
        return WorkflowResponse.model_validate(cloned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Variaveis do Workflow
# ---------------------------------------------------------------------------

@router.get(
    "/workflows/{workflow_id}/variables",
    response_model=list[WorkflowParam],
)
async def get_workflow_variables(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[WorkflowParam]:
    """Retorna a lista de variaveis globais declaradas no workflow."""
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )
    raw = workflow.definition.get("variables", []) if workflow.definition else []
    return [WorkflowParam.model_validate(v) for v in raw]


@router.get(
    "/workflows/{workflow_id}/variables/schema",
    response_model=VariablesSchemaResponse,
)
async def get_workflow_variables_schema(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> VariablesSchemaResponse:
    """Retorna o schema de variaveis do workflow com opcoes de conexao pre-carregadas.

    Para cada variavel do tipo ``connection``, a resposta inclui a lista de
    conectores compativeis (filtrados por ``connection_type`` quando declarado),
    evitando uma segunda chamada do frontend.
    """
    from sqlalchemy import and_, or_, select as sa_select
    from app.models.connection import Connection
    from app.models import Project

    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    raw_vars = workflow.definition.get("variables", []) if workflow.definition else []
    all_variables = [WorkflowParam.model_validate(v) for v in raw_vars]

    # Filtra so variaveis de fato referenciadas por nos ativos —
    # evita pedir valor para variaveis declaradas mas nao usadas (ou usadas
    # apenas em nos desativados via data.enabled=False).
    referenced = _collect_referenced_vars(workflow.definition)
    variables = [v for v in all_variables if v.name in referenced]

    # ── Variaveis herdadas de sub-workflows ─────────────────────────────
    # Tanto ``call_workflow`` quanto ``loop`` invocam sub-fluxos via
    # ``_invoke_subworkflow``; em ambos os casos as variaveis do sub-fluxo
    # precisam aparecer como herdadas no pai. ``_extract_subworkflow_ref``
    # normaliza a diferenca de campos (``version`` vs ``workflow_version``).
    # Nomes que colidem com variaveis do pai sao ignorados (o pai ja pede
    # o valor e o runtime faz auto-forward).
    from app.services.workflow_service import _extract_subworkflow_ref  # noqa: WPS433

    inherited_variables: list[InheritedVariable] = []
    parent_var_names = {v.name for v in all_variables}
    seen_inherited: set[tuple[UUID, str]] = set()

    # Pass 1: coleta todas as refs (sub_wf_id, version_spec normalizado) na
    # ordem em que aparecem nos nodes, preservando a ordem final de resposta.
    # version_spec normalizado: string "latest" ou int exato.
    sub_refs: list[tuple[UUID, str | int]] = []
    latest_ids: set[UUID] = set()
    exact_pairs: list[tuple[UUID, int]] = []
    for node in (workflow.definition.get("nodes") if workflow.definition else []) or []:
        ref = _extract_subworkflow_ref(node)
        if ref is None:
            continue
        sub_wf_id, version_spec = ref

        if version_spec == "latest" or version_spec is None:
            sub_refs.append((sub_wf_id, "latest"))
            latest_ids.add(sub_wf_id)
        else:
            try:
                version_num = int(version_spec)
            except (TypeError, ValueError):
                continue  # version invalida — skip silencioso, mesmo comportamento de antes
            sub_refs.append((sub_wf_id, version_num))
            exact_pairs.append((sub_wf_id, version_num))

    # Pass 2: 3 queries batched em vez de 2*N (nome + versao por sub-workflow).
    latest_by_wf: dict[UUID, WorkflowVersion] = {}
    exact_by_pair: dict[tuple[UUID, int], WorkflowVersion] = {}
    names_by_id: dict[UUID, str] = {}

    if sub_refs:
        if latest_ids:
            # Subquery agrega MAX(version) publicada por workflow_id; join traz
            # a linha completa de WorkflowVersion correspondente.
            latest_subq = (
                sa_select(
                    WorkflowVersion.workflow_id.label("wf_id"),
                    func.max(WorkflowVersion.version).label("max_v"),
                )
                .where(
                    WorkflowVersion.workflow_id.in_(latest_ids),
                    WorkflowVersion.published.is_(True),
                )
                .group_by(WorkflowVersion.workflow_id)
            ).subquery()
            latest_stmt = sa_select(WorkflowVersion).join(
                latest_subq,
                and_(
                    WorkflowVersion.workflow_id == latest_subq.c.wf_id,
                    WorkflowVersion.version == latest_subq.c.max_v,
                ),
            )
            for wv in (await db.execute(latest_stmt)).scalars().all():
                latest_by_wf[wv.workflow_id] = wv

        if exact_pairs:
            # OR de ANDs — funciona em qualquer dialeto (evita tuple_ IN que
            # pode ter suporte irregular em alguns drivers).
            exact_stmt = sa_select(WorkflowVersion).where(
                or_(
                    *[
                        and_(
                            WorkflowVersion.workflow_id == wf_id,
                            WorkflowVersion.version == ver,
                        )
                        for wf_id, ver in exact_pairs
                    ]
                )
            )
            for wv in (await db.execute(exact_stmt)).scalars().all():
                exact_by_pair[(wv.workflow_id, wv.version)] = wv

        all_sub_ids = {wid for wid, _ in sub_refs}
        if all_sub_ids:
            names_result = await db.execute(
                sa_select(Workflow.id, Workflow.name).where(Workflow.id.in_(all_sub_ids))
            )
            for row_id, row_name in names_result.all():
                names_by_id[row_id] = row_name

    # Pass 3: itera em memoria, reproduzindo a logica original node a node.
    for sub_wf_id, version_spec in sub_refs:
        if version_spec == "latest":
            version_row = latest_by_wf.get(sub_wf_id)
        else:
            version_row = exact_by_pair.get((sub_wf_id, version_spec))
        if version_row is None:
            continue  # sub-workflow/versao inexistente — mesmo skip de antes

        sub_def = version_row.definition if isinstance(version_row.definition, dict) else {}
        sub_raw_vars = sub_def.get("variables") or []
        sub_referenced = _collect_referenced_vars(sub_def)
        sub_name = names_by_id.get(sub_wf_id) or str(sub_wf_id)

        for raw in sub_raw_vars:
            try:
                param = WorkflowParam.model_validate(raw)
            except Exception:  # noqa: BLE001
                continue
            if param.name not in sub_referenced:
                continue
            if param.name in parent_var_names:
                continue  # o pai ja declara — auto-forward no runtime
            key = (sub_wf_id, param.name)
            if key in seen_inherited:
                continue
            seen_inherited.add(key)

            # ui_group permite que o ExecuteWorkflowDialog agrupe no formulario.
            group_label = f"Herdadas de: {sub_name}"
            grouped = param.model_copy(update={"ui_group": group_label})
            inherited_variables.append(
                InheritedVariable(
                    variable=grouped,
                    sub_workflow_id=sub_wf_id,
                    sub_workflow_name=sub_name,
                    sub_workflow_version=version_row.version,
                )
            )

    # ── Resolucao de conectores (tanto para vars do pai quanto herdadas) ──
    conn_var_names: list[str] = []
    conn_types_by_var: dict[str, str | None] = {}
    for v in variables:
        if v.type == "connection":
            conn_var_names.append(v.name)
            conn_types_by_var[v.name] = v.connection_type
    for inh in inherited_variables:
        if inh.variable.type == "connection":
            # Sobrescreve se colidir — inherited sempre vem com ui_group, nao
            # colide com parent porque filtramos acima.
            conn_var_names.append(inh.variable.name)
            conn_types_by_var[inh.variable.name] = inh.variable.connection_type

    if not conn_var_names:
        return VariablesSchemaResponse(
            variables=variables,
            inherited_variables=inherited_variables,
        )

    # Resolve workspace_id efetivo (proprio ou via projeto)
    workspace_id = workflow.workspace_id
    if workspace_id is None and workflow.project_id is not None:
        proj_row = await db.execute(
            sa_select(Project.workspace_id).where(Project.id == workflow.project_id)
        )
        workspace_id = proj_row.scalar_one_or_none()

    # Mapeamento de nomes UI -> tipo DB (WorkflowParam usa "postgres", DB usa "postgresql")
    _TYPE_MAP: dict[str, str] = {
        "postgres": "postgresql",
        "mysql": "mysql",
        "sqlserver": "sqlserver",
        "oracle": "oracle",
        "mongodb": "mongodb",
    }

    # Busca conectores publicos do workspace/projeto
    filters = []
    if workspace_id is not None and workflow.project_id is not None:
        filters.append(
            or_(
                Connection.workspace_id == workspace_id,
                Connection.project_id == workflow.project_id,
            )
        )
    elif workspace_id is not None:
        filters.append(Connection.workspace_id == workspace_id)
    elif workflow.project_id is not None:
        filters.append(Connection.project_id == workflow.project_id)
    else:
        return VariablesSchemaResponse(
            variables=variables,
            inherited_variables=inherited_variables,
        )

    conn_result = await db.execute(
        sa_select(Connection.id, Connection.name, Connection.type)
        .where(
            *filters,
            or_(
                Connection.is_public.is_(True),
                Connection.created_by_id == current_user.id,
            ),
        )
        .order_by(Connection.name)
    )
    all_connections = [
        ConnectionOptionResponse(id=row.id, name=row.name, type=row.type)
        for row in conn_result.mappings().all()
    ]

    connection_options: dict[str, list[ConnectionOptionResponse]] = {}
    for var_name in conn_var_names:
        ctype = conn_types_by_var.get(var_name)
        db_type = _TYPE_MAP.get(ctype or "", "") if ctype else None
        if db_type:
            connection_options[var_name] = [c for c in all_connections if c.type == db_type]
        else:
            connection_options[var_name] = list(all_connections)

    return VariablesSchemaResponse(
        variables=variables,
        connection_options=connection_options,
        inherited_variables=inherited_variables,
    )


@router.put(
    "/workflows/{workflow_id}/variables",
    response_model=list[WorkflowParam],
)
async def update_workflow_variables(
    workflow_id: UUID,
    payload: WorkflowVariablesSchema,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> list[WorkflowParam]:
    """Persiste a lista de variaveis globais em definition['variables'].

    Substitui completamente a lista existente. Envie uma lista vazia para
    remover todas as variaveis.
    """
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )
    definition = dict(workflow.definition or {})
    definition["variables"] = [v.model_dump() for v in payload.variables]
    workflow.definition = definition
    await db.flush()
    await db.refresh(workflow)
    await db.commit()
    return payload.variables


# ---------------------------------------------------------------------------
# Upload de arquivos para nos e variaveis file_upload
# ---------------------------------------------------------------------------

_ALLOWED_UPLOAD_EXTENSIONS = frozenset({
    ".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet", ".txt",
})


async def _resolve_project_workflow_ids(
    db: AsyncSession, workflow: Workflow
) -> list[str]:
    """Lista workflow_ids que compartilham o mesmo project_id (ou
    workspace_id se project for None) — usado pra somar quota do
    projeto no upload service."""
    if workflow.project_id is not None:
        stmt = select(Workflow.id).where(Workflow.project_id == workflow.project_id)
    elif workflow.workspace_id is not None:
        stmt = select(Workflow.id).where(
            Workflow.workspace_id == workflow.workspace_id,
            Workflow.project_id.is_(None),
        )
    else:
        return [str(workflow.id)]
    rows = (await db.execute(stmt)).scalars().all()
    return [str(r) for r in rows]


@router.post(
    "/workflows/{workflow_id}/uploads",
    status_code=status.HTTP_201_CREATED,
)
async def upload_workflow_file(
    workflow_id: UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict:
    """Faz upload de um arquivo pra uso em nos (csv_input, excel_input)
    e variaveis ``file_upload``.

    Retorna ``{file_id, url, size_bytes, original_filename, sha256, deduped}``.
    O nome ``url`` e o path interno do arquivo no host. Para referenciar
    em config de no, prefira o URI scheme ``shift-upload://<file_id>`` —
    desacopla a definicao do workflow da localizacao fisica do arquivo.

    Limites:
        - Extensao deve estar em {.csv .tsv .xlsx .xls .json .parquet .txt}.
        - Arquivo individual: ``settings.WORKFLOW_UPLOAD_MAX_FILE_MB``.
        - Quota agregada por projeto: ``settings.WORKFLOW_UPLOAD_QUOTA_PER_PROJECT_MB``.

    Dedup: se o mesmo conteudo (sha256) ja existe neste workflow, devolve
    o file_id existente sem regravar — ``deduped: true`` na resposta.
    """
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    filename = file.filename or "upload"
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Extensao '{ext}' nao permitida. Aceitas: {sorted(_ALLOWED_UPLOAD_EXTENSIONS)}",
        )

    max_bytes = settings.WORKFLOW_UPLOAD_MAX_FILE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Arquivo excede o limite de "
                f"{settings.WORKFLOW_UPLOAD_MAX_FILE_MB} MB."
            ),
        )

    # Quota por projeto — soma uploads de todos workflows do mesmo project_id
    quota_bytes = settings.WORKFLOW_UPLOAD_QUOTA_PER_PROJECT_MB * 1024 * 1024
    project_workflow_ids = await _resolve_project_workflow_ids(db, workflow)
    used_bytes = workflow_file_upload_service.get_quota_used_for_workflows(
        project_workflow_ids
    )
    if used_bytes + len(content) > quota_bytes:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Quota do projeto excedida ("
                f"{settings.WORKFLOW_UPLOAD_QUOTA_PER_PROJECT_MB} MB). "
                f"Em uso: {used_bytes // (1024*1024)} MB, "
                f"este arquivo: {len(content) // (1024*1024)} MB."
            ),
        )

    result = workflow_file_upload_service.save(
        workflow_id=str(workflow_id),
        filename=filename,
        content=content,
    )
    return result


@router.get("/workflows/{workflow_id}/uploads")
async def list_workflow_files(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> list[dict]:
    """Lista arquivos uploadados deste workflow.

    Retorna lista ordenada por ``created_at`` desc com:
    ``[{file_id, original_filename, size_bytes, created_at,
    last_accessed_at, sha256}]``. Path absoluto NAO e exposto.
    """
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    files = workflow_file_upload_service.list_files(str(workflow_id))
    # Remove path absoluto (vazamento desnecessario; UI usa shift-upload://)
    public = [
        {
            "file_id": f["file_id"],
            "original_filename": f.get("original_filename"),
            "size_bytes": f.get("size_bytes", 0),
            "sha256": f.get("sha256"),
            "created_at": f.get("created_at"),
            "last_accessed_at": f.get("last_accessed_at"),
        }
        for f in files
    ]
    public.sort(key=lambda f: f.get("created_at") or "", reverse=True)
    return public


# ---------------------------------------------------------------------------
# Inspecao de arquivos Excel (lista de sheets)
# ---------------------------------------------------------------------------


class ExcelSheetsRequest(BaseModel):
    """Body do endpoint de inspecao de sheets."""

    file_ref: str = Field(
        ...,
        min_length=1,
        description=(
            "Referencia ao arquivo Excel: pode ser shift-upload://<file_id>, "
            "UUID puro, http(s)://, ou path local."
        ),
    )


class ExcelSheetsResponse(BaseModel):
    sheets: list[str]


@router.post(
    "/workflows/{workflow_id}/excel/sheets",
    response_model=ExcelSheetsResponse,
)
async def list_excel_sheets(
    workflow_id: UUID,
    body: ExcelSheetsRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> ExcelSheetsResponse:
    """Abre o arquivo Excel referenciado e devolve os nomes das sheets.

    Usado pelo frontend pra popular o dropdown 'Nome da Aba' do nó
    excel_input — UX bem melhor que digitar o nome a mao.

    Resolucao do file_ref:
        - ``shift-upload://<id>`` ou UUID puro -> resolve via
          workflow_file_upload_service.
        - ``http://`` / ``https://`` -> baixa em tempfile e abre.
        - path local -> abre direto.

    Auth: mesmo escopo do upload (CONSULTANT do workspace dono do
    workflow).

    Performance: usa openpyxl read_only — abre o arquivo, le a lista
    de sheets do .xlsx (1 entrada do ZIP), fecha. Sem iterar linhas.
    """
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    # Resolve referencia → path local (download se necessario)
    from app.services.workflow.nodes._input_helpers import resolve_upload_url  # noqa: PLC0415

    try:
        resolved = resolve_upload_url(
            f"excel-sheets-inspection",
            body.file_ref,
            {"workflow_id": str(workflow_id)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Se for URL remota, baixa em tempfile.
    from pathlib import Path  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    cleanup_path: Path | None = None
    if resolved.lower().startswith(("http://", "https://")):
        import httpx  # noqa: PLC0415

        suffix = ".xlsx" if resolved.lower().endswith(".xlsx") else ".xls"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        cleanup_path = Path(tmp.name)
        tmp.close()
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                with client.stream("GET", resolved) as resp:
                    resp.raise_for_status()
                    with cleanup_path.open("wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
        except Exception as exc:
            cleanup_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Falha ao baixar arquivo: {exc}",
            )
        local_path = cleanup_path
    else:
        local_path = Path(resolved)
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Arquivo nao encontrado.",
            )

    try:
        try:
            import openpyxl  # noqa: PLC0415
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="openpyxl nao instalado no backend.",
            )
        try:
            wb = openpyxl.load_workbook(
                str(local_path), read_only=True, data_only=False
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Nao foi possivel abrir o arquivo Excel: {exc}",
            )
        try:
            sheets = list(wb.sheetnames)
        finally:
            wb.close()
    finally:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)

    return ExcelSheetsResponse(sheets=sheets)


@router.delete(
    "/workflows/{workflow_id}/uploads/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow_file(
    workflow_id: UUID,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> None:
    """Remove um arquivo uploadado. 404 se file_id nao existir.

    AVISO: workflows que referenciem ``shift-upload://<file_id>`` em
    configuracao de nos vao falhar na proxima execucao com mensagem
    clara. Nao ha verificacao de uso aqui — caller assume a remocao.
    """
    workflow = await workflow_crud_service.get(db, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    removed = workflow_file_upload_service.delete(str(workflow_id), file_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arquivo '{file_id}' nao encontrado.",
        )
