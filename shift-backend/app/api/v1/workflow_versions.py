"""
Endpoints para gerenciar versoes publicadas de workflows.

Uma ``WorkflowVersion`` e um snapshot imutavel da ``definition`` +
``io_schema`` de um workflow, consumido por nos ``call_workflow`` em
outros workflows. A lista de workflows ``/callable`` exibe apenas os
que ja possuem ao menos uma versao publicada — alimenta o picker do
editor no frontend.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models import User, Workflow, WorkflowVersion
from app.schemas.workflow import (
    CallableWorkflowSummary,
    WorkflowIOSchema,
    WorkflowVersionCreate,
    WorkflowVersionResponse,
)

router = APIRouter(tags=["workflow-versions"])


@router.post(
    "/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_workflow_version(
    workflow_id: UUID,
    payload: WorkflowVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowVersionResponse:
    """Publica uma nova versao do workflow."""
    workflow = await db.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    definition = payload.definition if payload.definition is not None else workflow.definition
    if not isinstance(definition, dict) or not definition.get("nodes"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workflow nao possui definition publicavel (sem nodes).",
        )

    # Calcula o proximo numero de versao monotonico.
    result = await db.execute(
        sa.select(sa.func.coalesce(sa.func.max(WorkflowVersion.version), 0)).where(
            WorkflowVersion.workflow_id == workflow_id
        )
    )
    next_version = int(result.scalar_one() or 0) + 1

    io_schema = payload.io_schema

    version = WorkflowVersion(
        workflow_id=workflow_id,
        version=next_version,
        definition=definition,
        input_schema=[p.model_dump() for p in io_schema.inputs],
        output_schema=[p.model_dump() for p in io_schema.outputs],
        published=True,
        created_by_id=current_user.id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    return _version_to_response(version)


@router.get(
    "/workflows/{workflow_id}/versions",
    response_model=list[WorkflowVersionResponse],
)
async def list_workflow_versions(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[WorkflowVersionResponse]:
    """Lista as versoes publicadas de um workflow (mais recentes primeiro)."""
    result = await db.execute(
        sa.select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version.desc())
    )
    versions = result.scalars().all()
    return [_version_to_response(v) for v in versions]


@router.get(
    "/workflows/callable",
    response_model=list[CallableWorkflowSummary],
)
async def list_callable_workflows(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CallableWorkflowSummary]:
    """Retorna workflows que possuem ao menos uma versao publicada.

    Usado pelo picker do no ``call_workflow`` no editor.
    """
    result = await db.execute(
        sa.select(
            Workflow.id,
            Workflow.name,
            Workflow.description,
            WorkflowVersion.version,
        )
        .join(WorkflowVersion, WorkflowVersion.workflow_id == Workflow.id)
        .where(WorkflowVersion.published.is_(True))
        .order_by(Workflow.name.asc(), WorkflowVersion.version.asc())
    )

    by_workflow: dict[UUID, dict] = {}
    for wf_id, name, desc, version_num in result.all():
        entry = by_workflow.get(wf_id)
        if entry is None:
            by_workflow[wf_id] = {
                "workflow_id": wf_id,
                "name": name,
                "description": desc,
                "versions": [version_num],
                "latest_version": version_num,
            }
        else:
            entry["versions"].append(version_num)
            if version_num > entry["latest_version"]:
                entry["latest_version"] = version_num

    return [CallableWorkflowSummary(**entry) for entry in by_workflow.values()]


def _version_to_response(version: WorkflowVersion) -> WorkflowVersionResponse:
    """Converte o model para schema API — tolera input_schema/output_schema raw."""
    return WorkflowVersionResponse(
        id=version.id,
        workflow_id=version.workflow_id,
        version=version.version,
        input_schema=version.input_schema or [],
        output_schema=version.output_schema or [],
        published=version.published,
        created_at=version.created_at,
    )
