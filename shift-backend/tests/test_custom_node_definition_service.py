"""
Testes de validacao dos schemas Pydantic de CustomNodeDefinition.

O servico em si (``custom_node_definition_service``) e um wrapper CRUD
direto sobre SQLAlchemy — sua logica e exercitada em integracao
com o Postgres real (tipos UUID/JSONB nativos) e nao aqui. Estes
testes focam na validacao estrutural dos payloads.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.custom_node_definition import (
    CustomNodeDefinitionCreate,
    CustomNodeDefinitionUpdate,
)


def _valid_blueprint() -> dict:
    return {
        "tables": [
            {
                "alias": "nota",
                "table": "NOTA",
                "role": "header",
                "cardinality": "one",
                "columns": ["NUMERO", "VALOR_TOTAL"],
                "returning": ["ID"],
            },
            {
                "alias": "item",
                "table": "NOTAITEM",
                "role": "child",
                "parent_alias": "nota",
                "fk_map": [{"child_column": "NOTA_ID", "parent_returning": "ID"}],
                "cardinality": "one",
                "columns": ["PRODUTO", "QUANTIDADE"],
                "returning": [],
            },
        ]
    }


class TestScopeValidation:
    def test_both_workspace_and_project_raises(self) -> None:
        with pytest.raises(ValidationError, match="exatamente um entre"):
            CustomNodeDefinitionCreate(
                name="teste",
                workspace_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                blueprint=_valid_blueprint(),
            )

    def test_neither_workspace_nor_project_raises(self) -> None:
        with pytest.raises(ValidationError, match="exatamente um entre"):
            CustomNodeDefinitionCreate(
                name="teste",
                blueprint=_valid_blueprint(),
            )

    def test_only_workspace_is_valid(self) -> None:
        obj = CustomNodeDefinitionCreate(
            name="teste",
            workspace_id=uuid.uuid4(),
            blueprint=_valid_blueprint(),
        )
        assert obj.project_id is None
        assert obj.workspace_id is not None

    def test_only_project_is_valid(self) -> None:
        obj = CustomNodeDefinitionCreate(
            name="teste",
            project_id=uuid.uuid4(),
            blueprint=_valid_blueprint(),
        )
        assert obj.workspace_id is None
        assert obj.project_id is not None


class TestDefaults:
    def test_create_defaults(self) -> None:
        obj = CustomNodeDefinitionCreate(
            name="teste",
            workspace_id=uuid.uuid4(),
            blueprint=_valid_blueprint(),
        )
        assert obj.category == "output"
        assert obj.kind == "composite_insert"
        assert obj.version == 1
        assert obj.is_published is False
        assert obj.description is None
        assert obj.icon is None
        assert obj.color is None


class TestBlueprintValidation:
    def test_blueprint_requires_at_least_one_table(self) -> None:
        with pytest.raises(ValidationError):
            CustomNodeDefinitionCreate(
                name="teste",
                workspace_id=uuid.uuid4(),
                blueprint={"tables": []},
            )

    def test_blueprint_cardinality_many_not_accepted(self) -> None:
        blueprint = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "cardinality": "many",
                    "columns": ["NUMERO"],
                    "returning": [],
                }
            ]
        }
        with pytest.raises(ValidationError):
            CustomNodeDefinitionCreate(
                name="teste",
                workspace_id=uuid.uuid4(),
                blueprint=blueprint,
            )

    def test_valid_blueprint_dumps_back_to_dict(self) -> None:
        obj = CustomNodeDefinitionCreate(
            name="teste",
            workspace_id=uuid.uuid4(),
            blueprint=_valid_blueprint(),
        )
        dumped = obj.blueprint.model_dump()
        assert len(dumped["tables"]) == 2
        assert dumped["tables"][0]["alias"] == "nota"
        assert dumped["tables"][1]["parent_alias"] == "nota"


class TestUpdateSchema:
    def test_all_fields_optional(self) -> None:
        obj = CustomNodeDefinitionUpdate()
        assert obj.model_dump(exclude_none=True) == {}

    def test_partial_update_keeps_only_set_fields(self) -> None:
        obj = CustomNodeDefinitionUpdate(name="Novo nome", is_published=True)
        dumped = obj.model_dump(exclude_none=True)
        assert dumped == {"name": "Novo nome", "is_published": True}

    def test_update_accepts_new_blueprint(self) -> None:
        obj = CustomNodeDefinitionUpdate(blueprint=_valid_blueprint())
        assert obj.blueprint is not None
        assert len(obj.blueprint.tables) == 2
