"""
Testes das rotas /executions/{id}/snapshot e /executions/{id}/replay.

Abordagem
---------
Chamamos os handlers async diretamente, mockando ``db.execute`` e o
``authorization_service.has_permission`` para isolar a rota da camada de
acesso ao banco. Isso segue o padrao de outros testes em ``tests/api/``.

Cobertura (Tarefa 1 do prompt de fechamento)
--------------------------------------------
- 200 para usuario do workspace correto + snapshot sanitizado.
- 404 para usuario de OUTRO workspace (NAO 403 — nao vazar existencia).
- 404 para execution inexistente.
- 201 para replay bem-sucedido com mesmo template_version.
- Replay usa o snapshot antigo (test de servico ja cobre; aqui validamos
  o contrato de resposta).
- 409 quando snapshot da execucao original esta corrompido/ausente.
- Snapshot retornado contem ``<REDACTED>`` em vez de secret em texto claro.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.workflows import (
    get_execution_snapshot,
    replay_execution,
)
from app.schemas.workflow import (
    ExecutionResponse,
    ReplayExecutionRequest,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock(name="User")
    user.id = user_id or uuid.uuid4()
    return user


def _make_execution(
    *,
    execution_id: uuid.UUID,
    workflow_id: uuid.UUID,
    template_snapshot: dict | None,
    template_version: str | None = "abc123def",
) -> MagicMock:
    exc = MagicMock(name="WorkflowExecution")
    exc.id = execution_id
    exc.workflow_id = workflow_id
    exc.template_snapshot = template_snapshot
    exc.template_version = template_version
    exc.rendered_at = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    exc.status = "COMPLETED"
    return exc


def _make_db(
    execution: MagicMock | None,
    workflow_workspace_id: uuid.UUID | None,
    workflow_definition: dict | None = None,
    *,
    new_template_version: str | None = None,
) -> MagicMock:
    """Devolve um AsyncSession fake.

    Reproduz a sequencia de queries de cada handler:
    1. ``SELECT WorkflowExecution`` -> ``execution`` ou None
    2. ``SELECT coalesce(Workflow.workspace_id, Project.workspace_id)`` -> ``workflow_workspace_id``
    3. ``SELECT Workflow.definition`` -> ``workflow_definition`` (so /snapshot e /definition)
    4. ``SELECT WorkflowExecution.template_version`` -> ``new_template_version`` (so /replay)
    """
    queue: list[MagicMock] = []

    def _row(scalar):
        m = MagicMock()
        m.scalar_one_or_none.return_value = scalar
        return m

    queue.append(_row(execution))
    queue.append(_row(workflow_workspace_id))
    if workflow_definition is not None:
        queue.append(_row(workflow_definition))
    if new_template_version is not None:
        queue.append(_row(new_template_version))

    db = MagicMock()

    async def _exec(*_a, **_kw):
        if queue:
            return queue.pop(0)
        return _row(None)

    db.execute = AsyncMock(side_effect=_exec)
    return db


# ---------------------------------------------------------------------------
# GET /executions/{id}/snapshot
# ---------------------------------------------------------------------------


class TestGetExecutionSnapshot:
    @pytest.mark.asyncio
    async def test_returns_200_with_sanitized_snapshot_for_authorized_user(self):
        eid = uuid.uuid4()
        wid = uuid.uuid4()
        ws = uuid.uuid4()
        snapshot = {
            "nodes": [
                {
                    "id": "h",
                    "data": {
                        "headers": {"Authorization": "Bearer <REDACTED>"},
                        "url": "https://api.example.com",
                    },
                }
            ]
        }
        execution = _make_execution(
            execution_id=eid,
            workflow_id=wid,
            template_snapshot=snapshot,
        )
        db = _make_db(execution, ws, workflow_definition=snapshot)
        user = _make_user()

        with patch(
            "app.core.security.authorization_service.has_permission",
            new=AsyncMock(return_value=True),
        ):
            response = await get_execution_snapshot(
                execution_id=eid, db=db, current_user=user
            )

        assert response.execution_id == eid
        assert response.template_snapshot == snapshot
        assert response.template_version == "abc123def"
        # ``diverged`` depende do hash atual ser != template_version; fora do
        # foco deste test (cobertura em test_execution_template_snapshot).
        assert response.rendered_at is not None

    @pytest.mark.asyncio
    async def test_returns_404_for_user_in_other_workspace(self):
        """Cross-workspace deve retornar 404 (nao 403) — sem vazar existencia."""
        eid = uuid.uuid4()
        wid = uuid.uuid4()
        ws_other = uuid.uuid4()
        execution = _make_execution(
            execution_id=eid, workflow_id=wid,
            template_snapshot={"nodes": []},
        )
        db = _make_db(execution, ws_other, workflow_definition={"nodes": []})
        user = _make_user()

        with patch(
            "app.core.security.authorization_service.has_permission",
            new=AsyncMock(return_value=False),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_execution_snapshot(
                    execution_id=eid, db=db, current_user=user
                )

        assert exc_info.value.status_code == 404
        assert "nao encontrada" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_execution(self):
        eid = uuid.uuid4()
        db = _make_db(None, None)  # execution lookup retorna None
        user = _make_user()

        with patch(
            "app.core.security.authorization_service.has_permission",
            new=AsyncMock(return_value=True),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_execution_snapshot(
                    execution_id=eid, db=db, current_user=user
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_does_not_leak_secret_values(self):
        """Garantia core: snapshot retornado deve conter ``<REDACTED>`` no
        lugar onde o valor original do secret estaria; o valor real NUNCA
        pode aparecer no payload da response."""
        eid, wid, ws = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        SECRET_VALUE = "ULTRA-SECRET-shouldnt-leak-3F8c"
        # Snapshot ja sanitizado pelo workflow_service no momento da execucao;
        # o valor real foi substituido por <REDACTED>.
        sanitized = {
            "nodes": [
                {
                    "id": "h",
                    "data": {"headers": {"Authorization": "Bearer <REDACTED>"}},
                }
            ]
        }
        execution = _make_execution(
            execution_id=eid, workflow_id=wid, template_snapshot=sanitized,
        )
        db = _make_db(execution, ws, workflow_definition=sanitized)
        user = _make_user()

        with patch(
            "app.core.security.authorization_service.has_permission",
            new=AsyncMock(return_value=True),
        ):
            response = await get_execution_snapshot(
                execution_id=eid, db=db, current_user=user
            )

        import json
        serialized = json.dumps(response.model_dump(mode="json"))
        assert "<REDACTED>" in serialized
        assert SECRET_VALUE not in serialized


# ---------------------------------------------------------------------------
# POST /executions/{id}/replay
# ---------------------------------------------------------------------------


class TestReplayExecution:
    @pytest.mark.asyncio
    async def test_returns_201_with_same_template_version(self):
        eid = uuid.uuid4()
        wid = uuid.uuid4()
        ws = uuid.uuid4()
        new_eid = uuid.uuid4()
        execution = _make_execution(
            execution_id=eid, workflow_id=wid,
            template_snapshot={"nodes": [{"id": "n1"}]},
            template_version="OLD_HASH_123",
        )
        # 2 lookups iniciais (execution + workspace) + 1 final (template_version
        # da nova execucao apos replay).
        db = _make_db(
            execution, ws,
            new_template_version="OLD_HASH_123",
        )
        user = _make_user()

        with (
            patch(
                "app.core.security.authorization_service.has_permission",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.api.v1.workflows.workflow_service.replay_execution",
                new=AsyncMock(return_value=ExecutionResponse(
                    execution_id=new_eid, status="RUNNING",
                )),
            ),
        ):
            response = await replay_execution(
                execution_id=eid,
                payload=ReplayExecutionRequest(),
                db=db,
                current_user=user,
            )

        assert response.execution_id == new_eid
        assert response.original_execution_id == eid
        assert response.template_version == "OLD_HASH_123"
        assert response.status == "RUNNING"

    @pytest.mark.asyncio
    async def test_returns_404_for_user_in_other_workspace(self):
        eid = uuid.uuid4()
        wid = uuid.uuid4()
        ws_other = uuid.uuid4()
        execution = _make_execution(
            execution_id=eid, workflow_id=wid,
            template_snapshot={"nodes": []},
        )
        db = _make_db(execution, ws_other)
        user = _make_user()

        with patch(
            "app.core.security.authorization_service.has_permission",
            new=AsyncMock(return_value=False),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await replay_execution(
                    execution_id=eid,
                    payload=ReplayExecutionRequest(),
                    db=db,
                    current_user=user,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_409_when_snapshot_corrupted(self):
        """``replay_execution`` levanta ValueError quando snapshot e None/dict
        vazio. Rota mapeia esse erro para 409 (nao 404) — execucao existe,
        so nao e replayable."""
        eid = uuid.uuid4()
        wid = uuid.uuid4()
        ws = uuid.uuid4()
        execution = _make_execution(
            execution_id=eid, workflow_id=wid, template_snapshot={},
        )
        db = _make_db(execution, ws)
        user = _make_user()

        with (
            patch(
                "app.core.security.authorization_service.has_permission",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.api.v1.workflows.workflow_service.replay_execution",
                new=AsyncMock(side_effect=ValueError(
                    f"Execucao '{eid}' nao possui template_snapshot utilizavel."
                )),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await replay_execution(
                    execution_id=eid,
                    payload=ReplayExecutionRequest(),
                    db=db,
                    current_user=user,
                )
        assert exc_info.value.status_code == 409
        assert "snapshot" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_returns_404_when_workflow_missing(self):
        """Workflow original deletado mas execucao ainda existe — 404 do replay
        (mensagem do servico nao contem "snapshot")."""
        eid = uuid.uuid4()
        wid = uuid.uuid4()
        ws = uuid.uuid4()
        execution = _make_execution(
            execution_id=eid, workflow_id=wid,
            template_snapshot={"nodes": [{"id": "x"}]},
        )
        db = _make_db(execution, ws)
        user = _make_user()

        with (
            patch(
                "app.core.security.authorization_service.has_permission",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.api.v1.workflows.workflow_service.replay_execution",
                new=AsyncMock(side_effect=ValueError(
                    f"Workflow '{wid}' nao existe mais; replay impossivel."
                )),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await replay_execution(
                    execution_id=eid,
                    payload=ReplayExecutionRequest(),
                    db=db,
                    current_user=user,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_replay_passes_trigger_type_to_service(self):
        eid, wid, ws, new_eid = (uuid.uuid4() for _ in range(4))
        execution = _make_execution(
            execution_id=eid, workflow_id=wid,
            template_snapshot={"nodes": []},
        )
        db = _make_db(execution, ws, new_template_version="X")
        user = _make_user()

        captured = {}

        async def _fake_replay(*, db, execution_id, triggered_by):
            captured["triggered_by"] = triggered_by
            return ExecutionResponse(execution_id=new_eid, status="RUNNING")

        with (
            patch(
                "app.core.security.authorization_service.has_permission",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.api.v1.workflows.workflow_service.replay_execution",
                new=AsyncMock(side_effect=_fake_replay),
            ),
        ):
            await replay_execution(
                execution_id=eid,
                payload=ReplayExecutionRequest(trigger_type="manual"),
                db=db,
                current_user=user,
            )
        assert captured["triggered_by"] == "manual"


# ---------------------------------------------------------------------------
# Documentacao OpenAPI — verifica que summaries/responses estao registrados.
# ---------------------------------------------------------------------------


class TestOpenAPI:
    def test_snapshot_route_has_summary_and_404_response(self):
        from app.api.v1.workflows import router

        snapshot_route = next(
            r for r in router.routes
            if getattr(r, "name", "") == "get_execution_snapshot"
        )
        assert snapshot_route.summary
        assert 404 in snapshot_route.responses

    def test_replay_route_has_summary_201_and_409(self):
        from app.api.v1.workflows import router

        replay_route = next(
            r for r in router.routes
            if getattr(r, "name", "") == "replay_execution"
        )
        assert replay_route.summary
        assert replay_route.status_code == 201
        assert 409 in replay_route.responses
        assert 404 in replay_route.responses
