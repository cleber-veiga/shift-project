"""
Endpoints de export/import de workflows (Fase 9).

- ``POST /workflows/{workflow_id}/export?format=sql|python|yaml`` — devolve
  um arquivo standalone (text/plain, text/x-python, application/x-yaml).
  HTTP 422 com corpo estruturado quando o workflow contem nos nao-suportados.
- ``POST /workflows/import`` — recebe um YAML versionado e cria um workflow
  draft no workspace/projeto destino.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.security import require_permission
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate, WorkflowResponse
from app.services.workflow.exporters import (
    PythonExporter,
    SQLExporter,
    UnsupportedNodeError,
)
from app.services.workflow.serializers import (
    YAML_SCHEMA_VERSION,
    YamlVersionError,
    from_yaml,
    to_yaml,
)
from app.services.workflow_crud_service import workflow_crud_service


router = APIRouter(tags=["workflows"])


_FORMAT_TO_CONTENT_TYPE = {
    "sql": "text/plain; charset=utf-8",
    "python": "text/x-python; charset=utf-8",
    "yaml": "application/x-yaml; charset=utf-8",
}

_FORMAT_TO_EXTENSION = {
    "sql": "sql",
    "python": "py",
    "yaml": "yaml",
}


def _slugify(name: str | None) -> str:
    if not name:
        return "workflow"
    safe = "".join(
        c if c.isalnum() or c in {"-", "_"} else "_"
        for c in name.strip().lower()
    )
    safe = safe.strip("_") or "workflow"
    return safe[:80]


@router.post("/workflows/{workflow_id}/export")
async def export_workflow(
    workflow_id: UUID,
    format: Literal["sql", "python", "yaml"] = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> Response:
    """Exporta um workflow para SQL DuckDB, Python standalone ou YAML versionado.

    Retorna 422 com lista estruturada quando ha nos nao suportados (V1):

        {
          "error": "Cannot export workflow: 2 unsupported nodes.",
          "unsupported": [{"node_id": "...", "node_type": "...", "reason": "..."}, ...]
        }
    """
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' nao encontrado.",
        )

    definition = dict(workflow.definition or {})
    # Inclui workflow_id/name no payload p/ os exportadores popularem o cabecalho.
    definition.setdefault("workflow_id", str(workflow.id))
    definition.setdefault("workflow_name", workflow.name)

    try:
        if format == "sql":
            body = SQLExporter().export(definition)
        elif format == "python":
            body = PythonExporter().export(definition)
        else:  # yaml
            body = to_yaml(
                definition,
                name=workflow.name,
                workflow_id=str(workflow.id),
            )
    except UnsupportedNodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": str(exc),
                "unsupported": exc.unsupported,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": str(exc)},
        ) from exc

    filename = f"{_slugify(workflow.name)}.{_FORMAT_TO_EXTENSION[format]}"
    return Response(
        content=body,
        media_type=_FORMAT_TO_CONTENT_TYPE[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/workflows/import",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_workflow(
    workspace_id: UUID | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> WorkflowResponse:
    """Cria um workflow draft a partir de um arquivo YAML exportado pelo Shift.

    Exatamente um entre ``workspace_id`` e ``project_id`` deve ser informado —
    mesmo contrato do ``POST /workflows`` regular.
    """
    if not file.filename or not file.filename.lower().endswith((".yaml", ".yml")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esperado arquivo .yaml/.yml.",
        )

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo nao e UTF-8 valido.",
        ) from exc

    try:
        parsed = from_yaml(text)
    except YamlVersionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": str(exc),
                "found_version": exc.found,
                "expected_version": exc.expected,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    payload = WorkflowCreate(
        name=parsed.get("name") or (file.filename.rsplit(".", 1)[0] or "imported"),
        description=None,
        project_id=project_id,
        workspace_id=workspace_id,
        is_template=False,
        definition=parsed["definition"],
        tags=[],
    )
    try:
        workflow = await workflow_crud_service.create(db, payload)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return WorkflowResponse.model_validate(workflow)


__all__ = ["router", "YAML_SCHEMA_VERSION"]
