"""
Servico CRUD de definicoes de nos personalizados.

Escopo XOR (workspace OU projeto). Visibilidade: qualquer pessoa com
permissao de leitura no escopo ve todas as definicoes daquele escopo —
nao ha nocao de publico/privado (diferente de Connection).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_node_definition import CustomNodeDefinition
from app.schemas.custom_node_definition import (
    CustomNodeDefinitionCreate,
    CustomNodeDefinitionUpdate,
    _validate_form_schema_against_blueprint,
)
from app.schemas.workflow import CompositeBlueprint


class CustomNodeDefinitionService:
    """CRUD de CustomNodeDefinition."""

    async def create(
        self,
        db: AsyncSession,
        data: CustomNodeDefinitionCreate,
        created_by_id: UUID,
    ) -> CustomNodeDefinition:
        definition = CustomNodeDefinition(
            workspace_id=data.workspace_id,
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            category=data.category,
            icon=data.icon,
            color=data.color,
            kind=data.kind,
            version=data.version,
            is_published=data.is_published,
            blueprint=data.blueprint.model_dump(),
            form_schema=(
                data.form_schema.model_dump() if data.form_schema is not None else None
            ),
            created_by_id=created_by_id,
        )
        db.add(definition)
        await db.flush()
        await db.refresh(definition)
        return definition

    async def list(
        self,
        db: AsyncSession,
        workspace_id: UUID,
    ) -> list[CustomNodeDefinition]:
        """Lista definicoes do workspace."""
        result = await db.execute(
            select(CustomNodeDefinition)
            .where(CustomNodeDefinition.workspace_id == workspace_id)
            .order_by(CustomNodeDefinition.name, CustomNodeDefinition.version)
        )
        return list(result.scalars().all())

    async def list_for_project(
        self,
        db: AsyncSession,
        project_id: UUID,
        workspace_id: UUID,
    ) -> list[CustomNodeDefinition]:
        """Lista definicoes do projeto e do workspace pai (herdadas)."""
        result = await db.execute(
            select(CustomNodeDefinition)
            .where(
                or_(
                    CustomNodeDefinition.workspace_id == workspace_id,
                    CustomNodeDefinition.project_id == project_id,
                )
            )
            .order_by(CustomNodeDefinition.name, CustomNodeDefinition.version)
        )
        return list(result.scalars().all())

    async def get(
        self,
        db: AsyncSession,
        definition_id: UUID,
    ) -> CustomNodeDefinition | None:
        result = await db.execute(
            select(CustomNodeDefinition).where(
                CustomNodeDefinition.id == definition_id
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        definition_id: UUID,
        data: CustomNodeDefinitionUpdate,
    ) -> CustomNodeDefinition | None:
        definition = await self.get(db, definition_id)
        if definition is None:
            return None

        updates = data.model_dump(exclude_none=True)

        if "blueprint" in updates:
            updates["blueprint"] = data.blueprint.model_dump() if data.blueprint else None

        # form_schema may arrive alone — cross-validate against effective blueprint
        # (incoming or currently persisted).
        if "form_schema" in updates and data.form_schema is not None:
            effective_bp_dict = updates.get("blueprint") or definition.blueprint
            if effective_bp_dict is not None:
                _validate_form_schema_against_blueprint(
                    data.form_schema,
                    CompositeBlueprint.model_validate(effective_bp_dict),
                )
            updates["form_schema"] = data.form_schema.model_dump()

        for field, value in updates.items():
            setattr(definition, field, value)

        await db.flush()
        await db.refresh(definition)
        return definition

    async def duplicate(
        self,
        db: AsyncSession,
        definition_id: UUID,
        created_by_id: UUID,
    ) -> CustomNodeDefinition | None:
        """
        Cria uma nova definicao (clone) com version = max(version do mesmo
        nome no escopo) + 1 e ``is_published=False``. Preserva blueprint,
        form_schema, icon, color e category.

        Workflows ja salvos continuam apontando para a definicao original
        (snapshot em node.data); o admin publica a nova versao quando estiver
        pronta e pode excluir a antiga quando nao houver mais referencias.
        """
        source = await self.get(db, definition_id)
        if source is None:
            return None

        max_version = await db.scalar(
            select(func.max(CustomNodeDefinition.version)).where(
                CustomNodeDefinition.workspace_id == source.workspace_id,
                CustomNodeDefinition.project_id == source.project_id,
                CustomNodeDefinition.name == source.name,
            )
        )
        next_version = (max_version or source.version) + 1

        clone = CustomNodeDefinition(
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            name=source.name,
            description=source.description,
            category=source.category,
            icon=source.icon,
            color=source.color,
            kind=source.kind,
            version=next_version,
            is_published=False,
            blueprint=source.blueprint,
            form_schema=source.form_schema,
            created_by_id=created_by_id,
        )
        db.add(clone)
        await db.flush()
        await db.refresh(clone)
        return clone

    async def delete(
        self,
        db: AsyncSession,
        definition_id: UUID,
    ) -> bool:
        definition = await self.get(db, definition_id)
        if definition is None:
            return False
        await db.delete(definition)
        await db.flush()
        return True


custom_node_definition_service = CustomNodeDefinitionService()
