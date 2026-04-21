"""
Testes para resolucao de variaveis de workflow em tempo de execucao.

Cobre:
- _coerce_variable_value: coercao de tipos
- _validate_and_resolve_variables: required/default/tipo
- _substitute_vars_in_definition: substituicao em definicoes
- ConnectionRef: aceita UUID e {{vars.X}}, rejeita strings invalidas
- Round-trip via endpoints de execucao (mock de DB e connection_service)
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.workflow import (
    ConnectionRef,
    SqlDatabaseNodeConfig,
    CsvInputNodeConfig,
    WorkflowParam,
    TruncateTableNodeConfig,
    BulkInsertNodeConfig,
)
from app.services.workflow_service import (
    _coerce_variable_value,
    _substitute_vars_in_definition,
    _validate_and_resolve_variables,
)


# ---------------------------------------------------------------------------
# Testes de _coerce_variable_value
# ---------------------------------------------------------------------------

class TestCoerceVariableValue:
    def test_string_coercion(self):
        assert _coerce_variable_value("x", "string", 42) == "42"

    def test_secret_coercion(self):
        assert _coerce_variable_value("x", "secret", "token") == "token"

    def test_integer_valid(self):
        assert _coerce_variable_value("n", "integer", "10") == 10

    def test_integer_invalid(self):
        with pytest.raises(ValueError, match="inteiro"):
            _coerce_variable_value("n", "integer", "abc")

    def test_number_valid(self):
        assert _coerce_variable_value("f", "number", "3.14") == pytest.approx(3.14)

    def test_number_invalid(self):
        with pytest.raises(ValueError, match="numero"):
            _coerce_variable_value("f", "number", "nope")

    def test_boolean_true_variants(self):
        for v in ("true", "True", "TRUE", "1", "yes"):
            assert _coerce_variable_value("b", "boolean", v) is True

    def test_boolean_false_variants(self):
        for v in ("false", "False", "0", "no"):
            assert _coerce_variable_value("b", "boolean", v) is False

    def test_boolean_invalid(self):
        with pytest.raises(ValueError, match="booleano"):
            _coerce_variable_value("b", "boolean", "maybe")

    def test_connection_valid_uuid(self):
        uid = str(uuid.uuid4())
        result = _coerce_variable_value("c", "connection", uid)
        assert result == uid

    def test_connection_invalid(self):
        with pytest.raises(ValueError, match="UUID"):
            _coerce_variable_value("c", "connection", "not-a-uuid")

    def test_file_upload_passthrough(self):
        fid = str(uuid.uuid4())
        assert _coerce_variable_value("f", "file_upload", fid) == fid

    def test_object_passthrough(self):
        obj = {"key": "value"}
        assert _coerce_variable_value("o", "object", obj) is obj


# ---------------------------------------------------------------------------
# Testes de _validate_and_resolve_variables
# ---------------------------------------------------------------------------

class TestValidateAndResolveVariables:
    @pytest.mark.asyncio
    async def test_required_missing_raises(self):
        decls = [{"name": "conn", "type": "connection", "required": True}]
        with pytest.raises(ValueError, match="obrigatoria"):
            await _validate_and_resolve_variables(decls, {})

    @pytest.mark.asyncio
    async def test_required_provided(self):
        uid = str(uuid.uuid4())
        decls = [{"name": "conn", "type": "connection", "required": True}]
        result = await _validate_and_resolve_variables(decls, {"conn": uid})
        assert result["conn"] == uid

    @pytest.mark.asyncio
    async def test_optional_missing_uses_default(self):
        decls = [{"name": "x", "type": "string", "required": False, "default": "fallback"}]
        result = await _validate_and_resolve_variables(decls, {})
        assert result["x"] == "fallback"

    @pytest.mark.asyncio
    async def test_optional_missing_no_default(self):
        decls = [{"name": "x", "type": "string", "required": False, "default": None}]
        result = await _validate_and_resolve_variables(decls, {})
        assert result["x"] is None

    @pytest.mark.asyncio
    async def test_type_coercion_applied(self):
        decls = [{"name": "n", "type": "integer", "required": True}]
        result = await _validate_and_resolve_variables(decls, {"n": "42"})
        assert result["n"] == 42

    @pytest.mark.asyncio
    async def test_malformed_declaration_skipped(self):
        # invalid type should be skipped silently
        decls = [{"name": "x", "type": "nonexistent_type"}]
        result = await _validate_and_resolve_variables(decls, {"x": "val"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_vars_resolved(self):
        uid = str(uuid.uuid4())
        decls = [
            {"name": "conn", "type": "connection", "required": True},
            {"name": "label", "type": "string", "required": False, "default": "default_label"},
        ]
        result = await _validate_and_resolve_variables(decls, {"conn": uid})
        assert result["conn"] == uid
        assert result["label"] == "default_label"


# ---------------------------------------------------------------------------
# Testes de _substitute_vars_in_definition
# ---------------------------------------------------------------------------

class TestSubstituteVarsInDefinition:
    def test_no_vars_returns_original_shape(self):
        defn = {"nodes": [{"data": {"type": "manual"}}], "edges": []}
        result = _substitute_vars_in_definition(defn, {})
        assert result == defn

    def test_substitutes_connection_id(self):
        uid = str(uuid.uuid4())
        defn = {
            "nodes": [{"data": {"type": "sql_database", "connection_id": "{{vars.conn}}"}}],
            "edges": [],
        }
        result = _substitute_vars_in_definition(defn, {"conn": uid})
        assert result["nodes"][0]["data"]["connection_id"] == uid

    def test_substitutes_url_field(self):
        defn = {
            "nodes": [{"data": {"type": "csv_input", "url": "{{vars.arquivo}}"}}],
            "edges": [],
        }
        result = _substitute_vars_in_definition(defn, {"arquivo": "/tmp/test.csv"})
        assert result["nodes"][0]["data"]["url"] == "/tmp/test.csv"

    def test_partial_substitution_in_string(self):
        defn = {"nodes": [{"data": {"query": "SELECT * FROM {{vars.tabela}} LIMIT 10"}}]}
        result = _substitute_vars_in_definition(defn, {"tabela": "vendas"})
        assert result["nodes"][0]["data"]["query"] == "SELECT * FROM vendas LIMIT 10"

    def test_unknown_var_left_as_template(self):
        defn = {"nodes": [{"data": {"url": "{{vars.nao_declarada}}"}}]}
        result = _substitute_vars_in_definition(defn, {"outra": "val"})
        assert result["nodes"][0]["data"]["url"] == "{{vars.nao_declarada}}"

    def test_does_not_mutate_original(self):
        uid = str(uuid.uuid4())
        defn = {"nodes": [{"data": {"connection_id": "{{vars.conn}}"}}]}
        original_id = defn["nodes"][0]["data"]["connection_id"]
        _substitute_vars_in_definition(defn, {"conn": uid})
        assert defn["nodes"][0]["data"]["connection_id"] == original_id

    def test_nested_list_substitution(self):
        defn = {"tables": [{"conn": "{{vars.c1}}"}, {"conn": "{{vars.c2}}"}]}
        uid1, uid2 = str(uuid.uuid4()), str(uuid.uuid4())
        result = _substitute_vars_in_definition(defn, {"c1": uid1, "c2": uid2})
        assert result["tables"][0]["conn"] == uid1
        assert result["tables"][1]["conn"] == uid2


# ---------------------------------------------------------------------------
# Testes de ConnectionRef (schema)
# ---------------------------------------------------------------------------

class TestConnectionRef:
    def _make_config(self, conn_id: Any) -> SqlDatabaseNodeConfig:
        return SqlDatabaseNodeConfig(
            type="sql_database",
            connection_id=conn_id,
        )

    def test_accepts_uuid_object(self):
        uid = uuid.uuid4()
        config = self._make_config(uid)
        assert config.connection_id == uid

    def test_accepts_uuid_string(self):
        uid = str(uuid.uuid4())
        config = self._make_config(uid)
        assert config.connection_id == uuid.UUID(uid)

    def test_accepts_vars_template(self):
        config = self._make_config("{{vars.minha_conexao}}")
        assert config.connection_id == "{{vars.minha_conexao}}"

    def test_accepts_vars_template_with_spaces(self):
        config = self._make_config("{{ vars.conn }}")
        assert config.connection_id == "{{ vars.conn }}"

    def test_rejects_arbitrary_string(self):
        with pytest.raises(Exception):
            self._make_config("not-a-uuid-or-template")

    def test_rejects_wrong_prefix(self):
        with pytest.raises(Exception):
            self._make_config("{{context.conn}}")

    def test_truncate_table_has_connection_ref(self):
        uid = uuid.uuid4()
        config = TruncateTableNodeConfig(
            type="truncate_table",
            connection_id=str(uid),
            target_table="my_table",
        )
        assert config.connection_id == uid

    def test_bulk_insert_accepts_template(self):
        config = BulkInsertNodeConfig(
            type="bulk_insert",
            connection_id="{{vars.destino}}",
            target_table="target",
        )
        assert config.connection_id == "{{vars.destino}}"

    def test_csv_input_url_accepts_template(self):
        # url: str already accepts any string including templates
        config = CsvInputNodeConfig(
            type="csv_input",
            url="{{vars.arquivo}}",
        )
        assert config.url == "{{vars.arquivo}}"


# ---------------------------------------------------------------------------
# Teste de integracao do servico de execucao (mock DB + connection_service)
# ---------------------------------------------------------------------------

class TestWorkflowServiceVariableResolution:
    """Verifica que run() valida variaveis e passa context correto ao runner."""

    def _make_fake_db(self, workflow: Any, workspace_id: uuid.UUID) -> MagicMock:
        """Cria mock do AsyncSession com comportamento minimo necessario."""
        row_mock = MagicMock()
        row_mock.one_or_none.return_value = (workflow, workspace_id)

        db = MagicMock()
        db.execute = AsyncMock(return_value=row_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        # Simula DB-side UUID generation: quando add() e chamado com um objeto
        # sem id, atribui um UUID para que o codigo nao quebre em execution.id.
        def _fake_add(obj: Any) -> None:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

        db.add = _fake_add

        async def _fake_flush() -> None:
            pass  # id ja foi atribuido em add()

        db.flush = _fake_flush
        return db

    @pytest.mark.asyncio
    async def test_required_variable_missing_raises_before_execution(self):
        from app.services.workflow_service import WorkflowExecutionService

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [],
            "edges": [],
            "variables": [{"name": "conn", "type": "connection", "required": True}],
        }

        fake_db = self._make_fake_db(fake_workflow, workspace_id)

        service = WorkflowExecutionService()
        with pytest.raises(ValueError, match="obrigatoria"):
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={},
            )

    @pytest.mark.asyncio
    async def test_variable_values_reach_runner(self):
        """Verifica que resolved_vars chegam como variable_values para run_workflow."""
        from app.services.workflow_service import WorkflowExecutionService

        conn_uid = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [],
            "edges": [],
            "variables": [{"name": "conn", "type": "connection", "required": True}],
        }

        fake_db = self._make_fake_db(fake_workflow, workspace_id)
        captured: dict[str, Any] = {}

        async def fake_run_workflow(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"status": "completed", "node_executions": []}

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))
        fake_session.commit = AsyncMock()
        fake_session.add = MagicMock()

        with (
            patch(
                "app.services.workflow_service.connection_service.resolve_for_workflow",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.workflow_service.run_workflow", new=fake_run_workflow),
            patch(
                "app.services.workflow_service.async_session_factory",
                return_value=fake_session,
            ),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={"variable_values": {"conn": conn_uid}},
                wait=True,
            )

        assert captured.get("variable_values") == {"conn": conn_uid}

    @pytest.mark.asyncio
    async def test_connection_substituted_before_resolve(self):
        """Verifica que {{vars.conn}} e substituido antes de resolve_for_workflow."""
        from app.services.workflow_service import WorkflowExecutionService

        conn_uid = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [{"id": "n1", "type": "sql_database", "data": {
                "type": "sql_database",
                "connection_id": "{{vars.conn}}",
            }}],
            "edges": [],
            "variables": [{"name": "conn", "type": "connection", "required": True}],
        }

        fake_db = self._make_fake_db(fake_workflow, workspace_id)
        resolved_def: dict[str, Any] = {}

        async def fake_resolve(db, definition, **kw):
            resolved_def.update(definition)
            return {}

        async def fake_run_workflow(**kwargs):
            return {"status": "completed", "node_executions": []}

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))
        fake_session.commit = AsyncMock()
        fake_session.add = MagicMock()

        with (
            patch("app.services.workflow_service.connection_service.resolve_for_workflow", new=fake_resolve),
            patch("app.services.workflow_service.run_workflow", new=fake_run_workflow),
            patch("app.services.workflow_service.async_session_factory", return_value=fake_session),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={"variable_values": {"conn": conn_uid}},
                wait=True,
            )

        node_data = resolved_def.get("nodes", [{}])[0].get("data", {})
        assert node_data.get("connection_id") == conn_uid
