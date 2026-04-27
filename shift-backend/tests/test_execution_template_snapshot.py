"""
Testes para o snapshot imutavel de execucoes de workflow.

Cobre:
- ``_build_template_snapshot``: sanitiza secrets antes do hash;
  produz hash deterministico para mesma entrada.
- ``WorkflowExecutionService.run``: persiste template_snapshot/version/rendered_at
  com secrets redatados.
- ``WorkflowExecutionService.replay_execution``: cria nova execucao usando
  o snapshot da origem mesmo apos alteracao do workflow.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow_service import (
    REDACTED_PLACEHOLDER,
    WorkflowExecutionService,
    _build_template_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers de mock (replicados do test_workflow_execute_variables com extensao
# para suportar a busca de WorkflowExecution na replay).
# ---------------------------------------------------------------------------

def _make_fake_db(
    workflow: Any,
    workspace_id: uuid.UUID,
    execution: Any | None = None,
) -> MagicMock:
    """Fake AsyncSession que retorna ``workflow`` na 1a query e, quando
    informado, ``execution`` em queries subsequentes."""

    db = MagicMock()
    captured: list[Any] = []

    def _make_workflow_row() -> MagicMock:
        row = MagicMock()
        row.one_or_none.return_value = (workflow, workspace_id)
        return row

    def _make_scalar_row(value: Any) -> MagicMock:
        row = MagicMock()
        row.scalar_one_or_none.return_value = value
        return row

    queue = []

    if execution is not None:
        # 1a chamada (replay): WorkflowExecution lookup
        queue.append(_make_scalar_row(execution))
        # 2a: Workflow lookup
        queue.append(_make_scalar_row(workflow))
        # 3a: workspace_id lookup (caso project_id is not None)
        queue.append(_make_scalar_row(workspace_id))
    else:
        queue.append(_make_workflow_row())

    async def _execute(*args: Any, **kwargs: Any) -> MagicMock:
        # Devolve da fila enquanto houver, depois um row vazio (no-op).
        if queue:
            return queue.pop(0)
        return _make_scalar_row(None)

    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    def _fake_add(obj: Any) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        captured.append(obj)

    db.add = _fake_add
    db._captured = captured

    async def _fake_flush() -> None:
        pass

    db.flush = _fake_flush
    return db


def _make_fake_session() -> MagicMock:
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    fake_session.commit = AsyncMock()
    fake_session.add = MagicMock()
    return fake_session


# ---------------------------------------------------------------------------
# Testes unitarios do builder de snapshot
# ---------------------------------------------------------------------------


class TestBuildTemplateSnapshot:
    def test_secrets_substituted_with_redacted_placeholder(self):
        definition = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "http_request",
                    "data": {
                        "headers": {
                            "Authorization": "Bearer {{ vars.api_key }}",
                            "X-Project": "{{ vars.project_name }}",
                        },
                    },
                }
            ],
            "edges": [],
        }
        resolved_vars = {
            "api_key": "super-secret-token-123",
            "project_name": "demo",
        }
        snapshot, _digest = _build_template_snapshot(
            definition=definition,
            resolved_vars=resolved_vars,
            secret_names={"api_key"},
        )

        headers = snapshot["nodes"][0]["data"]["headers"]
        assert headers["Authorization"] == f"Bearer {REDACTED_PLACEHOLDER}"
        assert headers["X-Project"] == "demo"

    def test_secret_value_never_appears_in_serialized_snapshot(self):
        definition = {
            "nodes": [{"data": {"body": "token={{ vars.api_key }}&meta=ok"}}],
        }
        snapshot, _digest = _build_template_snapshot(
            definition=definition,
            resolved_vars={"api_key": "leak-me-please"},
            secret_names={"api_key"},
        )
        import json
        serialized = json.dumps(snapshot)
        assert "leak-me-please" not in serialized
        assert REDACTED_PLACEHOLDER in serialized

    def test_hash_is_deterministic_for_same_input(self):
        definition = {
            "nodes": [{"data": {"q": "{{ vars.label }}", "n": 5}}],
            "edges": [],
        }
        vars_ = {"label": "x"}
        _, hash_a = _build_template_snapshot(definition, vars_, set())
        _, hash_b = _build_template_snapshot(definition, vars_, set())
        assert hash_a == hash_b
        assert len(hash_a) == 64  # SHA-256 hex

    def test_hash_changes_when_definition_changes(self):
        vars_: dict[str, Any] = {}
        _, hash_a = _build_template_snapshot({"nodes": [{"id": "a"}]}, vars_, set())
        _, hash_b = _build_template_snapshot({"nodes": [{"id": "b"}]}, vars_, set())
        assert hash_a != hash_b

    def test_undeclared_secret_still_redacted_when_referenced(self):
        """Variavel marcada como secret mas sem valor fornecido: o template
        ``{{ vars.api_key }}`` ainda deve renderizar como ``<REDACTED>``."""
        definition = {"nodes": [{"data": {"h": "Bearer {{ vars.api_key }}"}}]}
        snapshot, _ = _build_template_snapshot(
            definition=definition,
            resolved_vars={},
            secret_names={"api_key"},
        )
        assert snapshot["nodes"][0]["data"]["h"] == f"Bearer {REDACTED_PLACEHOLDER}"

    def test_non_template_strings_pass_through_untouched(self):
        definition = {"nodes": [{"data": {"msg": "no templates here"}}]}
        snapshot, _ = _build_template_snapshot(definition, {}, set())
        assert snapshot["nodes"][0]["data"]["msg"] == "no templates here"

    def test_jinja_block_tags_are_sandboxed(self):
        """Strings com ``{% %}`` nao podem alcancar atributos perigosos.

        SandboxedEnvironment bloqueia acesso a __subclasses__ e similares;
        em caso de erro o helper devolve a string original.
        """
        # Tentativa de explorar Python internals via Jinja2.
        definition = {
            "nodes": [
                {"data": {"x": "{{ ().__class__.__bases__[0].__subclasses__() }}"}}
            ]
        }
        snapshot, _ = _build_template_snapshot(definition, {}, set())
        # Sandbox levanta SecurityError; helper devolve a string original.
        assert snapshot["nodes"][0]["data"]["x"].startswith("{{ ()")


# ---------------------------------------------------------------------------
# Testes do servico — persistencia do snapshot
# ---------------------------------------------------------------------------


class TestServicePersistsSnapshot:
    @pytest.mark.asyncio
    async def test_secret_redacted_in_persisted_snapshot(self):
        from app.models.workflow import WorkflowExecution

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {
            "nodes": [
                {
                    "id": "h",
                    "type": "http_request",
                    "data": {"url": "https://api.example.com",
                             "headers": {"Authorization": "Bearer {{ vars.api_key }}"}},
                }
            ],
            "edges": [],
            "variables": [{"name": "api_key", "type": "secret", "required": True}],
        }

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        async def fake_run_workflow(**_: Any) -> dict[str, Any]:
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

        with (
            patch(
                "app.services.workflow_service.connection_service.resolve_for_workflow",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.workflow_service.run_workflow",
                new=fake_run_workflow,
            ),
            patch(
                "app.services.workflow_service.async_session_factory",
                return_value=fake_session,
            ),
        ):
            service = WorkflowExecutionService()
            await service.run(
                db=fake_db,
                workflow_id=workflow_id,
                input_data={"variable_values": {"api_key": "ULTRA-SECRET"}},
                wait=True,
            )

        executions = [
            obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)
        ]
        assert len(executions) == 1
        exec_obj = executions[0]
        # snapshot esta presente, NOT NULL satisfeito
        assert exec_obj.template_snapshot is not None
        assert exec_obj.template_version is not None
        assert exec_obj.rendered_at is not None
        # secret jamais aparece em texto claro no snapshot
        import json
        serialized = json.dumps(exec_obj.template_snapshot)
        assert "ULTRA-SECRET" not in serialized
        assert REDACTED_PLACEHOLDER in serialized

    @pytest.mark.asyncio
    async def test_hash_persisted_matches_snapshot_content(self):
        import hashlib
        import json
        from app.models.workflow import WorkflowExecution

        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        fake_workflow.definition = {"nodes": [{"id": "x"}], "edges": []}

        fake_db = _make_fake_db(fake_workflow, workspace_id)

        async def fake_run_workflow(**_: Any) -> dict[str, Any]:
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

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
            await service.run(db=fake_db, workflow_id=workflow_id, wait=True)

        exec_obj = next(
            obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)
        )
        recomputed = hashlib.sha256(
            json.dumps(exec_obj.template_snapshot, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert exec_obj.template_version == recomputed


# ---------------------------------------------------------------------------
# Testes de replay — usa o snapshot antigo, ignora alteracoes posteriores
# ---------------------------------------------------------------------------


class TestReplayExecution:
    @pytest.mark.asyncio
    async def test_replay_uses_persisted_snapshot_not_current_definition(self):
        """Cenario: execucao roda com definicao A, workflow e editado para B,
        replay deve invocar o runner com A (do snapshot)."""
        from app.models.workflow import WorkflowExecution

        execution_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        snapshot_old = {
            "nodes": [{"id": "old", "data": {"q": "SELECT 1"}}],
            "edges": [],
        }

        fake_execution = MagicMock(spec=WorkflowExecution)
        fake_execution.id = execution_id
        fake_execution.workflow_id = workflow_id
        fake_execution.template_snapshot = snapshot_old
        fake_execution.template_version = "abc123"
        fake_execution.input_data = None

        fake_workflow = MagicMock()
        fake_workflow.id = workflow_id
        fake_workflow.project_id = None
        fake_workflow.workspace_id = workspace_id
        fake_workflow.status = "draft"
        # Definicao ATUAL diverge do snapshot (workflow foi editado).
        fake_workflow.definition = {
            "nodes": [{"id": "new", "data": {"q": "SELECT 2"}}],
            "edges": [],
        }

        fake_db = _make_fake_db(
            fake_workflow, workspace_id, execution=fake_execution
        )

        captured_run_args: dict[str, Any] = {}

        async def fake_run_workflow(**kwargs: Any) -> dict[str, Any]:
            captured_run_args.update(kwargs)
            return {"status": "completed", "node_executions": []}

        fake_session = _make_fake_session()

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
            patch(
                "app.services.workflow_service.execution_registry.register",
                new=AsyncMock(return_value=None),
            ),
        ):
            service = WorkflowExecutionService()
            response = await service.replay_execution(
                db=fake_db,
                execution_id=execution_id,
            )
            # Aguarda a task em background terminar para capturar run_args.
            import asyncio
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        # Replay devolveu uma nova execucao, distinta da original.
        assert response.execution_id != execution_id
        # A nova WorkflowExecution criada herda o snapshot e o version antigos.
        new_execs = [
            obj for obj in fake_db._captured if isinstance(obj, WorkflowExecution)
        ]
        assert len(new_execs) == 1
        new_exec = new_execs[0]
        assert new_exec.template_snapshot == snapshot_old
        assert new_exec.template_version == "abc123"
        # E o runner, quando chamado, recebe o snapshot — NAO a definicao
        # atual que foi editada.
        assert captured_run_args.get("workflow_payload") == snapshot_old

    @pytest.mark.asyncio
    async def test_replay_404_when_execution_missing(self):
        fake_db = MagicMock()
        empty_row = MagicMock()
        empty_row.scalar_one_or_none.return_value = None
        fake_db.execute = AsyncMock(return_value=empty_row)

        service = WorkflowExecutionService()
        with pytest.raises(ValueError, match="nao encontrada"):
            await service.replay_execution(db=fake_db, execution_id=uuid.uuid4())
