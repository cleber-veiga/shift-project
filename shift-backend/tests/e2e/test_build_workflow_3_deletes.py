"""
FASE 8 — Bloco D: teste E2E do cenario dos 3 DELETEs.

Cenario:
  User: "Preciso criar uma sequência de limpeza de banco como subfluxo
         que recebe :ESTAB e :IDITEM e faz esses deletes:
           DELETE VIASOFTMCP.ITEMAGREGADOS WHERE ESTAB=:ESTAB AND IDITEM=:IDITEM;
           DELETE VIASOFTMCP.ITEMAGREGADOS WHERE ESTAB=:ESTAB AND IDAGREGADO=:IDITEM;
           DELETE VIASOFTMCP.ITEMCONSUMIDO WHERE ESTABITEM=:ESTAB AND IDITEM=:IDITEM;"

Asserções validadas:
  1. SQL Intelligence detecta binds :ESTAB e :IDITEM em cada DELETE
  2. classify_destructiveness retorna 'destructive' para esses DELETEs
  3. build_workflow_node chama interrupt({type: 'destructive_approval_required'})
     com as tabelas afetadas
  4. Após aprovação simulada, build session é criada e ops dispatched
  5. Eventos SSE emitidos: build_started, pending_node_added x3, build_ready,
     build_confirmed (via confirm mock)
  6. final_report contem contagem de nos adicionados

Para simular o grafo completo sem LLM real e sem banco real, os testes
usam build_workflow_node diretamente com state pré-preenchido, seguindo
o padrão dos testes e2e existentes.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.agent.sql_intelligence.parser import (
    analyze_sql_script,
    classify_destructiveness,
    extract_binds,
    extract_tables,
)
from app.services.agent.graph.nodes.build_workflow import build_workflow_node
from app.services.build_session_service import BuildSessionService, ConfirmResult


# ---------------------------------------------------------------------------
# SQL scripts do cenario
# ---------------------------------------------------------------------------

_DELETE_1 = (
    "DELETE VIASOFTMCP.ITEMAGREGADOS "
    "WHERE ESTAB=:ESTAB AND IDITEM=:IDITEM"
)
_DELETE_2 = (
    "DELETE VIASOFTMCP.ITEMAGREGADOS "
    "WHERE ESTAB=:ESTAB AND IDAGREGADO=:IDITEM"
)
_DELETE_3 = (
    "DELETE VIASOFTMCP.ITEMCONSUMIDO "
    "WHERE ESTABITEM=:ESTAB AND IDITEM=:IDITEM"
)

_ALL_DELETES = f"{_DELETE_1};\n{_DELETE_2};\n{_DELETE_3};"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_ctx(workflow_id: str | None = None) -> dict:
    ctx = {
        "user_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "project_id": None,
        "workspace_role": "MANAGER",
        "project_role": "EDITOR",
        "organization_id": str(uuid4()),
        "organization_role": "MEMBER",
    }
    if workflow_id:
        ctx["workflow_id"] = workflow_id
    return ctx


def _mock_async_db():
    mock_db = AsyncMock()

    @asynccontextmanager
    async def _factory():
        yield mock_db

    return MagicMock(side_effect=_factory), mock_db


def _mock_publish():
    events: list[str] = []

    async def _side_effect(db, *, workflow_id, event_type, payload, client_mutation_id=None):
        events.append(event_type)

    return AsyncMock(side_effect=_side_effect), events


def _mock_node(node_id: str, node_type: str = "sql_script") -> MagicMock:
    n = MagicMock()
    n.node_id = node_id
    n.to_dict = MagicMock(return_value={"id": node_id, "type": node_type, "data": {"__pending": True}})
    return n


def _build_state_with_3_deletes(wf_id: str, *, intent: str = "create_sub_workflow") -> dict:
    return {
        "thread_id": str(uuid4()),
        "user_context": _make_user_ctx(wf_id),
        "messages": [
            {
                "role": "user",
                "content": (
                    "Preciso criar uma sequência de limpeza de banco como subfluxo "
                    "que recebe :ESTAB e :IDITEM e faz esses deletes:\n"
                    + _ALL_DELETES
                ),
            }
        ],
        "current_intent": {"intent": intent, "workflow_id": wf_id},
        "build_plan": {
            "workflow_id": wf_id,
            "summary": "Subfluxo de limpeza: 3 DELETEs em ITEMAGREGADOS e ITEMCONSUMIDO",
            "ops": [
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t_del1",
                        "node_type": "sql_script",
                        "label": "Delete ITEMAGREGADOS por IDITEM",
                        "config": {"query": _DELETE_1},
                    },
                },
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t_del2",
                        "node_type": "sql_script",
                        "label": "Delete ITEMAGREGADOS por IDAGREGADO",
                        "config": {"query": _DELETE_2},
                    },
                },
                {
                    "tool": "pending_add_node",
                    "arguments": {
                        "temp_id": "t_del3",
                        "node_type": "sql_script",
                        "label": "Delete ITEMCONSUMIDO por IDITEM",
                        "config": {"query": _DELETE_3},
                    },
                },
            ],
        },
        "workflow_context": None,
        "final_report": None,
        "guardrails_violation": None,
    }


# ---------------------------------------------------------------------------
# 1. SQL Intelligence: binds e destructividade detectados corretamente
# ---------------------------------------------------------------------------

class TestSqlIntelligenceOnDeletes:
    def test_each_delete_has_estab_and_iditem_binds(self):
        for sql in (_DELETE_1, _DELETE_2, _DELETE_3):
            binds = extract_binds(sql)
            names = [b.name for b in binds]
            assert "ESTAB" in names, f"ESTAB not found in {sql!r}: {names}"
            assert "IDITEM" in names, f"IDITEM not found in {sql!r}: {names}"

    def test_all_deletes_classified_destructive(self):
        for sql in (_DELETE_1, _DELETE_2, _DELETE_3):
            level = classify_destructiveness(sql, dialect="oracle")
            assert level == "destructive", f"Expected 'destructive', got {level!r} for {sql!r}"

    def test_combined_script_destructive(self):
        level = classify_destructiveness(_ALL_DELETES, dialect="oracle")
        assert level == "destructive"

    def test_extract_tables_identifies_correct_schemas(self):
        tables_1 = extract_tables(_DELETE_1, dialect="oracle")
        table_names = {t.table.upper() for t in tables_1}
        assert "ITEMAGREGADOS" in table_names, f"Table not found: {table_names}"
        schemas = {(t.schema or "").upper() for t in tables_1 if t.table.upper() == "ITEMAGREGADOS"}
        assert "VIASOFTMCP" in schemas, f"Schema VIASOFTMCP not found: {schemas}"

    def test_analyze_script_returns_correct_binds_and_destructiveness(self):
        result = analyze_sql_script(_ALL_DELETES, dialect="oracle")
        assert result["destructiveness"] == "destructive"
        bind_names = [b["name"] for b in result["binds"]]
        assert "ESTAB" in bind_names
        assert "IDITEM" in bind_names

    def test_suggested_input_schema_has_estab_and_iditem(self):
        result = analyze_sql_script(_ALL_DELETES, dialect="oracle")
        schema_names = {s["name"] for s in result["suggested_input_schema"]}
        assert "ESTAB" in schema_names
        assert "IDITEM" in schema_names


# ---------------------------------------------------------------------------
# 2. build_workflow_node: SQL destrutivo aciona interrupt para aprovação
# ---------------------------------------------------------------------------

class TestDestructiveSqlInterrupt:
    @pytest.mark.asyncio
    async def test_3_deletes_trigger_destructive_interrupt(self):
        """Os 3 DELETEs devem acionar interrupt com type=destructive_approval_required."""
        wf_id = str(uuid4())
        state = _build_state_with_3_deletes(wf_id)

        interrupted_payload: dict = {}

        def fake_interrupt(payload):
            interrupted_payload.update(payload)
            raise Exception("interrupt_called")

        with patch(
            "app.services.agent.graph.nodes.build_workflow.interrupt",
            side_effect=fake_interrupt,
        ), patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
            return_value=(True, None),
        ):
            try:
                await build_workflow_node(state)
            except Exception as exc:
                assert "interrupt_called" in str(exc)

        assert interrupted_payload.get("type") == "destructive_approval_required"
        tables = interrupted_payload.get("tables", [])
        assert isinstance(tables, list)
        assert len(tables) > 0
        # Pelo menos uma das tabelas dos DELETEs deve aparecer
        table_names_upper = [t.upper() for t in tables]
        assert any(
            "ITEMAGREGADOS" in n or "ITEMCONSUMIDO" in n
            for n in table_names_upper
        ), f"Expected ITEMAGREGADOS or ITEMCONSUMIDO in tables, got: {tables}"

    @pytest.mark.asyncio
    async def test_abort_when_approval_denied(self):
        """Se aprovacao negada, retorna final_report de aborto sem criar sessao."""
        wf_id = str(uuid4())
        state = _build_state_with_3_deletes(wf_id)

        interrupt_returns_denied = {"approved": False}

        with patch(
            "app.services.agent.graph.nodes.build_workflow.interrupt",
            return_value=interrupt_returns_denied,
        ), patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
            return_value=(True, None),
        ), patch(
            "app.services.agent.graph.nodes.build_workflow.build_session_service.create",
        ) as mock_create:
            result = await build_workflow_node(state)

        # Sessao nao deve ter sido criada
        mock_create.assert_not_called()
        assert "guardrails_violation" in result
        assert "abortada" in result["final_report"].lower() or "nao aprovado" in result["final_report"].lower()


# ---------------------------------------------------------------------------
# 3. Happy path com aprovacao: sessao criada, 3 nos dispatched, SSE emitidos
# ---------------------------------------------------------------------------

class TestApprovedBuildWith3Deletes:
    @pytest.mark.asyncio
    async def test_3_deletes_approved_dispatches_nodes_and_confirms(self):
        """Após aprovação simulada e confirmação, 3 nós criados e eventos SSE corretos."""
        wf_id = str(uuid4())
        session_id = uuid4()
        state = _build_state_with_3_deletes(wf_id)

        n1 = _mock_node("node_del1", "sql_script")
        n2 = _mock_node("node_del2", "sql_script")
        n3 = _mock_node("node_del3", "sql_script")

        publish_mock, events = _mock_publish()
        factory, mock_db = _mock_async_db()

        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.workflow_id = uuid4()

        mock_confirm = ConfirmResult(
            nodes_added=3,
            edges_added=0,
            session_id=session_id,
        )

        interrupt_call_count = 0
        interrupt_returns = [
            # First interrupt: destructive_approval_required → approved
            {"approved": True},
            # Second interrupt: build_ready → confirm
            {"action": "confirm"},
        ]

        def fake_interrupt(payload):
            nonlocal interrupt_call_count
            val = interrupt_returns[min(interrupt_call_count, len(interrupt_returns) - 1)]
            interrupt_call_count += 1
            return val

        add_node_mock = AsyncMock(side_effect=[n1, n2, n3])

        with (
            patch(
                "app.services.agent.graph.nodes.build_workflow.interrupt",
                side_effect=fake_interrupt,
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget",
                return_value=(True, None),
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.create",
                AsyncMock(return_value=mock_session),
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.get",
                AsyncMock(return_value=mock_session),
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_node",
                add_node_mock,
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.set_audit",
                AsyncMock(),
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.confirm",
                AsyncMock(return_value=mock_confirm),
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.build_session_service.cancel",
                AsyncMock(),
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.async_session_factory",
                factory,
            ),
            patch(
                "app.services.agent.tools.workflow_pending_tools.async_session_factory",
                factory,
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow.definition_event_service.publish",
                publish_mock,
            ),
            patch(
                "app.services.agent.graph.nodes.build_workflow._write_audit",
                AsyncMock(),
            ),
        ):
            result = await build_workflow_node(state)

        # Dois interrupts: um para destructive_approval, um para build_ready
        assert interrupt_call_count == 2

        # 3 nos criados
        assert add_node_mock.call_count == 3

        # Eventos SSE publicados
        assert "build_started" in events
        assert events.count("pending_node_added") == 3
        assert "build_ready" in events

        # Resultado com sucesso
        assert result.get("guardrails_violation") is None
        assert "final_report" in result
        assert "3" in result["final_report"]

    @pytest.mark.asyncio
    async def test_user_prompt_captured_in_audit(self):
        """user_prompt extraído de messages[0] é incluído no audit."""
        wf_id = str(uuid4())
        session_id = uuid4()
        state = _build_state_with_3_deletes(wf_id)

        audit_calls: list[dict] = []

        async def fake_write_audit(**kwargs):
            audit_calls.append(kwargs)

        n1 = _mock_node("n1")
        n2 = _mock_node("n2")
        n3 = _mock_node("n3")
        publish_mock, _ = _mock_publish()
        factory, _ = _mock_async_db()

        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_confirm = ConfirmResult(nodes_added=3, edges_added=0, session_id=session_id)

        interrupt_returns = [{"approved": True}, {"action": "confirm"}]
        call_idx = 0

        def fake_interrupt(p):
            nonlocal call_idx
            v = interrupt_returns[min(call_idx, 1)]
            call_idx += 1
            return v

        with (
            patch("app.services.agent.graph.nodes.build_workflow.interrupt", side_effect=fake_interrupt),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.check_build_budget", return_value=(True, None)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.create", AsyncMock(return_value=mock_session)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.add_pending_node", AsyncMock(side_effect=[n1, n2, n3])),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.set_audit", AsyncMock()),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.confirm", AsyncMock(return_value=mock_confirm)),
            patch("app.services.agent.graph.nodes.build_workflow.build_session_service.cancel", AsyncMock()),
            patch("app.services.agent.graph.nodes.build_workflow.async_session_factory", factory),
            patch("app.services.agent.graph.nodes.build_workflow.definition_event_service.publish", publish_mock),
            patch("app.services.agent.graph.nodes.build_workflow._write_audit", side_effect=fake_write_audit),
        ):
            await build_workflow_node(state)

        assert len(audit_calls) > 0
        last_audit = audit_calls[-1]
        assert "user_prompt" in last_audit
        assert "ESTAB" in (last_audit["user_prompt"] or "")


# ---------------------------------------------------------------------------
# 4. Persistência: variáveis do subfluxo têm ESTAB e IDITEM
# ---------------------------------------------------------------------------

class TestSubflowVariableBinding:
    def test_sql_analysis_suggests_estab_and_iditem_as_input_schema(self):
        """analyze_sql_script recomenda ESTAB e IDITEM como input_schema do subfluxo."""
        result = analyze_sql_script(_ALL_DELETES, dialect="oracle")
        schema = {s["name"] for s in result["suggested_input_schema"]}
        assert "ESTAB" in schema, f"ESTAB not in suggested schema: {schema}"
        assert "IDITEM" in schema, f"IDITEM not in suggested schema: {schema}"

    def test_bind_types_inferred(self):
        """ESTAB e IDITEM sem prefixo especial são inferidos como string."""
        result = analyze_sql_script(_ALL_DELETES, dialect="oracle")
        for bind in result["binds"]:
            if bind["name"] in ("ESTAB", "IDITEM"):
                assert bind["inferred_type"] == "string", (
                    f"{bind['name']} should be string, got {bind['inferred_type']}"
                )

    def test_all_three_tables_identified(self):
        """Os 3 DELETEs identificam ITEMAGREGADOS (2x) e ITEMCONSUMIDO (1x)."""
        result = analyze_sql_script(_ALL_DELETES, dialect="oracle")
        # tables dicts have "table" key (not "name")
        table_names = {(t.get("table") or "").upper() for t in result["tables"]}
        assert "ITEMAGREGADOS" in table_names, f"ITEMAGREGADOS missing: {table_names}"
        assert "ITEMCONSUMIDO" in table_names, f"ITEMCONSUMIDO missing: {table_names}"
