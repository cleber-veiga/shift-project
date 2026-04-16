"""
Servico de CRUD de Workflows e Templates.

Responsabilidades: criacao, atualizacao, listagem e clonagem de workflows.
A execucao permanece em workflow_service.py (SRP).
"""

import copy
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Workspace
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCloneRequest, WorkflowCreate, WorkflowUpdate


class WorkflowCrudService:
    """CRUD e clonagem de workflows."""

    async def create(
        self,
        db: AsyncSession,
        payload: WorkflowCreate,
    ) -> Workflow:
        """Cria um workflow ou template.

        Regras de validacao de escopo sao aplicadas nas rotas via require_permission.
        Aqui garantimos apenas a integridade do modelo: project_id OU workspace_id.
        """
        if payload.project_id is None and payload.workspace_id is None:
            raise ValueError("Um workflow deve pertencer a um projeto ou a um workspace.")

        workflow = Workflow(
            name=payload.name,
            description=payload.description,
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            is_template=payload.is_template,
            is_published=False,
            definition=payload.definition,
        )
        db.add(workflow)
        await db.flush()
        await db.refresh(workflow)
        return workflow

    async def get(self, db: AsyncSession, workflow_id: UUID) -> Workflow | None:
        """Retorna um workflow pelo ID."""
        result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        workflow_id: UUID,
        payload: WorkflowUpdate,
    ) -> Workflow:
        """Atualiza metadados ou definicao de um workflow existente."""
        workflow = await self.get(db, workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' nao encontrado.")

        if payload.name is not None:
            workflow.name = payload.name
        if payload.description is not None:
            workflow.description = payload.description
        if payload.definition is not None:
            workflow.definition = payload.definition
        if payload.is_template is not None:
            workflow.is_template = payload.is_template
        if payload.is_published is not None:
            workflow.is_published = payload.is_published
        if payload.status is not None:
            if payload.status not in ("draft", "published"):
                raise ValueError("Status deve ser 'draft' ou 'published'.")
            workflow.status = payload.status

        await db.flush()
        await db.refresh(workflow)
        return workflow

    async def delete(self, db: AsyncSession, workflow_id: UUID) -> None:
        """Remove um workflow pelo ID."""
        workflow = await self.get(db, workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' nao encontrado.")
        await db.delete(workflow)
        await db.flush()

    async def list_for_project(
        self,
        db: AsyncSession,
        project_id: UUID,
    ) -> list[Workflow]:
        """Lista workflows normais de um projeto (is_template=False)."""
        stmt = (
            select(Workflow)
            .where(Workflow.project_id == project_id)
            .where(Workflow.is_template.is_(False))
            .order_by(Workflow.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_workspace(
        self,
        db: AsyncSession,
        workspace_id: UUID,
    ) -> list[Workflow]:
        """Lista todos os workflows de um workspace (templates e nao-templates)."""
        stmt = (
            select(Workflow)
            .where(Workflow.workspace_id == workspace_id)
            .order_by(Workflow.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_templates_for_workspace(
        self,
        db: AsyncSession,
        workspace_id: UUID,
    ) -> list[Workflow]:
        """Lista templates publicados de um workspace."""
        stmt = (
            select(Workflow)
            .where(Workflow.workspace_id == workspace_id)
            .where(Workflow.is_template.is_(True))
            .where(Workflow.is_published.is_(True))
            .order_by(Workflow.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def publish(self, db: AsyncSession, workflow_id: UUID) -> Workflow:
        """Publica um template (is_published=True)."""
        workflow = await self.get(db, workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' nao encontrado.")
        if not workflow.is_template:
            raise ValueError("Somente templates podem ser publicados.")

        workflow.is_published = True
        await db.flush()
        await db.refresh(workflow)
        return workflow

    async def clone_template(
        self,
        db: AsyncSession,
        template_id: UUID,
        clone_request: WorkflowCloneRequest,
    ) -> Workflow:
        """Clona um template para um projeto destino.

        Percorre o JSON de 'definition' e substitui connection_ids conforme
        o mapeamento fornecido em clone_request.connection_mapping.
        """
        template = await self.get(db, template_id)
        if template is None:
            raise ValueError(f"Template '{template_id}' nao encontrado.")
        if not template.is_template:
            raise ValueError(f"Workflow '{template_id}' nao e um template.")
        if not template.is_published:
            raise ValueError(f"Template '{template_id}' nao esta publicado.")

        # Valida se o projeto destino existe
        result = await db.execute(
            select(Project).where(Project.id == clone_request.target_project_id)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(
                f"Projeto destino '{clone_request.target_project_id}' nao encontrado."
            )

        new_definition = _deep_replace_connections(
            copy.deepcopy(template.definition),
            clone_request.connection_mapping,
        )

        cloned = Workflow(
            name=template.name,
            description=template.description,
            project_id=clone_request.target_project_id,
            workspace_id=None,
            is_template=False,
            is_published=False,
            definition=new_definition,
        )
        db.add(cloned)
        await db.flush()
        await db.refresh(cloned)
        return cloned


def _deep_replace_connections(
    obj: Any,
    mapping: dict[str, UUID],
) -> Any:
    """Substitui recursivamente valores de connection_id em um JSON arbitrario.

    Percorre dicts e listas. Quando encontra a chave 'connection_id' com um
    valor presente no mapeamento, substitui pelo UUID novo (como string).
    """
    if not mapping:
        return obj

    # Normaliza o mapping para comparacao string→string
    str_mapping = {str(k): str(v) for k, v in mapping.items()}

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: str_mapping[str(v)] if k == "connection_id" and str(v) in str_mapping else _walk(v)
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    return _walk(obj)


workflow_crud_service = WorkflowCrudService()
