"""
Endpoints CRUD de Workflows e Templates.

Rotas de execucao permanecem em workflows.py.
"""

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
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
from app.core.security import require_permission
from app.models import User
from app.schemas.workflow import (
    ConnectionOptionResponse,
    VariablesSchemaResponse,
    WorkflowCloneRequest,
    WorkflowCreate,
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
    response_model=list[WorkflowResponse],
)
async def list_project_workflows(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("project", "CLIENT")),
) -> list[WorkflowResponse]:
    """Lista os workflows de um projeto."""
    workflows = await workflow_crud_service.list_for_project(db, project_id)
    return [WorkflowResponse.model_validate(w) for w in workflows]


@router.get(
    "/workspaces/{workspace_id}/workflows",
    response_model=list[WorkflowResponse],
)
async def list_workspace_workflows(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[WorkflowResponse]:
    """Lista todos os workflows de um workspace (inclui templates e workflows normais)."""
    workflows = await workflow_crud_service.list_for_workspace(db, workspace_id)
    return [WorkflowResponse.model_validate(w) for w in workflows]


@router.get(
    "/workspaces/{workspace_id}/templates",
    response_model=list[WorkflowResponse],
)
async def list_workspace_templates(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "VIEWER")),
) -> list[WorkflowResponse]:
    """Lista os templates publicados de um workspace."""
    templates = await workflow_crud_service.list_templates_for_workspace(db, workspace_id)
    return [WorkflowResponse.model_validate(t) for t in templates]


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
    from sqlalchemy import or_, select as sa_select
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

    # Identifica variaveis do tipo connection
    conn_vars = [v for v in variables if v.type == "connection"]
    if not conn_vars:
        return VariablesSchemaResponse(variables=variables)

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
        return VariablesSchemaResponse(variables=variables)

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
    for var in conn_vars:
        db_type = _TYPE_MAP.get(var.connection_type or "", "") if var.connection_type else None
        if db_type:
            connection_options[var.name] = [c for c in all_connections if c.type == db_type]
        else:
            connection_options[var.name] = list(all_connections)

    return VariablesSchemaResponse(variables=variables, connection_options=connection_options)


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
# Upload de arquivos para variaveis file_upload
# ---------------------------------------------------------------------------

_ALLOWED_UPLOAD_EXTENSIONS = frozenset({
    ".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet", ".txt",
})

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


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
    """Faz upload de um arquivo para uso em variaveis do tipo file_upload.

    Retorna `{file_id, url}` onde `url` e o path interno que deve ser
    passado como `variable_values.{nome_variavel}` ao executar o workflow.

    Extensoes aceitas: .csv .tsv .xlsx .xls .json .parquet .txt (max 50 MB).
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

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo excede o limite de {_MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )

    result = workflow_file_upload_service.save(
        workflow_id=str(workflow_id),
        filename=filename,
        content=content,
    )
    return result
