"""
Schemas Pydantic para definicoes de nos personalizados (custom node definitions).

Uma definicao e um blueprint reutilizavel de um no composto. Ao arrastar
para o canvas, o frontend copia o blueprint para ``node.data.blueprint``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.workflow import CompositeBlueprint


class CustomNodeFormField(BaseModel):
    """
    Metadado de apresentacao de um campo no formulario do no composto.

    ``key`` referencia uma coluna do blueprint no formato ``<alias>.<coluna>``.
    Os demais campos sao opcionais e afetam apenas a UI — a semantica de
    execucao permanece ditada por ``blueprint`` + ``field_mapping``.
    """

    key: str = Field(..., min_length=1, description="alias.coluna do blueprint")
    label: str | None = Field(default=None, max_length=255)
    help: str | None = Field(default=None, max_length=1024)
    required: bool = Field(default=False)
    hidden: bool = Field(default=False)
    default_upstream: str | None = Field(
        default=None,
        max_length=255,
        description="Nome de coluna upstream sugerida para auto-match",
    )


class CustomNodeFormSchema(BaseModel):
    """Schema de apresentacao do formulario (metadados de UI)."""

    fields: list[CustomNodeFormField] = Field(default_factory=list)


def _validate_form_schema_against_blueprint(
    form_schema: CustomNodeFormSchema | None,
    blueprint: CompositeBlueprint,
) -> None:
    if form_schema is None:
        return
    valid_keys: set[str] = set()
    for t in blueprint.tables:
        for col in t.columns:
            valid_keys.add(f"{t.alias}.{col}")
    seen: set[str] = set()
    for field in form_schema.fields:
        if field.key in seen:
            raise ValueError(f"Chave duplicada em form_schema: {field.key!r}.")
        seen.add(field.key)
        if field.key not in valid_keys:
            raise ValueError(
                f"form_schema.fields[].key {field.key!r} nao corresponde a "
                "nenhum alias.coluna do blueprint."
            )


class CustomNodeDefinitionCreate(BaseModel):
    """Payload para criar uma nova definicao de no personalizado."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    category: str = Field(default="output", min_length=1, max_length=50)
    icon: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=50)
    kind: Literal["composite_insert"] = Field(default="composite_insert")
    version: int = Field(default=1, ge=1)
    is_published: bool = Field(default=False)
    blueprint: CompositeBlueprint
    form_schema: CustomNodeFormSchema | None = None
    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "CustomNodeDefinitionCreate":
        if (self.workspace_id is None) == (self.project_id is None):
            raise ValueError("Informe exatamente um entre workspace_id e project_id.")
        _validate_form_schema_against_blueprint(self.form_schema, self.blueprint)
        return self


class CustomNodeDefinitionUpdate(BaseModel):
    """Payload para atualizar parcialmente uma definicao."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    icon: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=50)
    version: int | None = Field(default=None, ge=1)
    is_published: bool | None = None
    blueprint: CompositeBlueprint | None = None
    form_schema: CustomNodeFormSchema | None = None

    @model_validator(mode="after")
    def validate_form_schema_local(self) -> "CustomNodeDefinitionUpdate":
        # Cross-field validation against blueprint only when both are in the
        # same patch. If only form_schema is present, the service must re-validate
        # against the stored blueprint.
        if self.form_schema is not None and self.blueprint is not None:
            _validate_form_schema_against_blueprint(self.form_schema, self.blueprint)
        return self


class CustomNodeDefinitionResponse(BaseModel):
    """Representacao publica de uma definicao."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    category: str
    icon: str | None = None
    color: str | None = None
    kind: str
    version: int
    is_published: bool
    blueprint: dict
    form_schema: dict | None = None
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
