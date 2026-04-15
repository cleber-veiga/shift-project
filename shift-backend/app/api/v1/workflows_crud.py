"""
Endpoints CRUD de Workflows e Templates.

Rotas de execucao permanecem em workflows.py.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from app.schemas.workflow import (
    WorkflowCloneRequest,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowUpdate,
)
from app.services.workflow_crud_service import workflow_crud_service

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
    _=Depends(require_permission("workspace", "VIEWER")),
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
    _=Depends(require_permission("workspace", "VIEWER")),
) -> WorkflowResponse:
    """Atualiza metadados ou a definicao JSON de um workflow."""
    try:
        workflow = await workflow_crud_service.update(db, workflow_id, payload)
        await db.commit()
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
    _=Depends(require_permission("workspace", "VIEWER")),
) -> None:
    """Remove um workflow."""
    try:
        await workflow_crud_service.delete(db, workflow_id)
        await db.commit()
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
