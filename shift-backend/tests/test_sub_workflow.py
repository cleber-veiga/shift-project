"""
Testes de sub-workflows (Fase 3).

Cobre:
- ``WorkflowParam`` / ``WorkflowIOSchema`` (validacao de nomes duplicados).
- Processadores ``workflow_input`` e ``workflow_output``.
- ``run_workflow`` com ``call_stack`` detectando ciclo e profundidade maxima.
- ``call_workflow`` fazendo version pinning, validando inputs/outputs e
  isolando contexto do pai (sem vazar ``upstream_results``).

Testes evitam dependencia de Postgres real monkeypatchando helpers de
carga de ``WorkflowVersion`` e ``run_workflow``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.orchestration.flows.dynamic_runner import (
    SubWorkflowCycleError,
    SubWorkflowDepthError,
    run_workflow,
)
from app.schemas.workflow import WorkflowIOSchema, WorkflowParam
from app.services.workflow.nodes import sub_workflow as sub_mod
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow.nodes.sub_workflow import (
    CallWorkflowProcessor,
    WorkflowInputProcessor,
    WorkflowOutputProcessor,
)


# ---------------------------------------------------------------------------
# WorkflowParam / WorkflowIOSchema
# ---------------------------------------------------------------------------

class TestWorkflowIOSchema:
    def test_accepts_valid_params(self) -> None:
        schema = WorkflowIOSchema(
            inputs=[WorkflowParam(name="cliente_id", type="string")],
            outputs=[WorkflowParam(name="total", type="number", required=False)],
        )
        assert schema.inputs[0].name == "cliente_id"
        assert schema.outputs[0].required is False

    def test_duplicate_input_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicado"):
            WorkflowIOSchema(
                inputs=[
                    WorkflowParam(name="x", type="string"),
                    WorkflowParam(name="x", type="integer"),
                ],
            )

    def test_param_name_pattern_enforced(self) -> None:
        with pytest.raises(ValueError):
            WorkflowParam(name="123bad", type="string")


# ---------------------------------------------------------------------------
# Processors workflow_input / workflow_output
# ---------------------------------------------------------------------------

class TestWorkflowInputProcessor:
    def test_exposes_input_data_as_output_field(self) -> None:
        proc = WorkflowInputProcessor()
        ctx = {"input_data": {"cliente_id": "42", "valor": 100}}
        result = proc.process("n1", {"output_field": "data"}, ctx)
        assert result["status"] == "completed"
        assert result["data"] == {"cliente_id": "42", "valor": 100}


class TestWorkflowOutputProcessor:
    def test_updates_workflow_output_accumulator(self) -> None:
        proc = WorkflowOutputProcessor()
        accumulator: dict[str, Any] = {}
        ctx = {
            "workflow_output": accumulator,
            "input_data": {"cliente_id": "42"},
            "upstream_results": {
                "prev": {"data": {"valor": 999}},
            },
        }
        result = proc.process(
            "out",
            {"mapping": {
                "cliente": "{input_data.cliente_id}",
                "valor_total": "{upstream_results.prev.data.valor}",
            }},
            ctx,
        )
        assert result["status"] == "completed"
        assert accumulator == {"cliente": "42", "valor_total": 999}

    def test_invalid_mapping_type_raises(self) -> None:
        proc = WorkflowOutputProcessor()
        with pytest.raises(NodeProcessingError, match="mapping"):
            proc.process("out", {"mapping": "nao-eh-dict"}, {"workflow_output": {}})


# ---------------------------------------------------------------------------
# run_workflow: cycle + max_depth
# ---------------------------------------------------------------------------

class TestSubWorkflowGuards:
    def test_cycle_in_call_stack_raises(self) -> None:
        wf_id = str(uuid4())
        with pytest.raises(SubWorkflowCycleError, match="Ciclo"):
            asyncio.run(
                run_workflow(
                    workflow_payload={"nodes": [], "edges": []},
                    workflow_id=wf_id,
                    call_stack=[wf_id],
                )
            )

    def test_depth_exceeded_raises(self) -> None:
        stack = [str(uuid4()) for _ in range(5)]  # len == SUBWORKFLOW_MAX_DEPTH
        with pytest.raises(SubWorkflowDepthError, match="Profundidade"):
            asyncio.run(
                run_workflow(
                    workflow_payload={"nodes": [], "edges": []},
                    workflow_id=str(uuid4()),
                    call_stack=stack,
                )
            )

    def test_call_stack_populated_in_context(self) -> None:
        """O execution_context precisa carregar call_stack + current_id para
        nos ``call_workflow`` aninhados enxergarem a cadeia."""
        parent_id = str(uuid4())
        grand_id = str(uuid4())
        # Executa um workflow com apenas um no workflow_input para forcar
        # passagem de contexto. O processor vai ver call_stack no context.
        captured: dict[str, Any] = {}

        class _Spy(WorkflowInputProcessor):
            def process(self, node_id, config, context):
                captured.update(
                    call_stack=list(context.get("call_stack") or []),
                    max_depth=context.get("max_depth"),
                )
                return super().process(node_id, config, context)

        # Injeta o spy diretamente no registry para este teste.
        from app.services.workflow.nodes import _PROCESSOR_REGISTRY
        original = _PROCESSOR_REGISTRY["workflow_input"]
        _PROCESSOR_REGISTRY["workflow_input"] = _Spy
        try:
            result = asyncio.run(
                run_workflow(
                    workflow_payload={
                        "nodes": [{
                            "id": "n1",
                            "type": "workflow_input",
                            "data": {"type": "workflow_input"},
                        }],
                        "edges": [],
                    },
                    workflow_id=parent_id,
                    call_stack=[grand_id],
                )
            )
        finally:
            _PROCESSOR_REGISTRY["workflow_input"] = original

        assert result["status"] == "completed"
        assert captured["call_stack"] == [grand_id, parent_id]
        assert captured["max_depth"] == 5


# ---------------------------------------------------------------------------
# CallWorkflowProcessor: version pinning, input/output validation, isolation
# ---------------------------------------------------------------------------

def _fake_version(
    *,
    version: int = 1,
    input_schema: list[dict] | None = None,
    output_schema: list[dict] | None = None,
    definition: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        version=version,
        input_schema=input_schema or [],
        output_schema=output_schema or [],
        definition=definition or {"nodes": [], "edges": []},
    )


class TestCallWorkflowProcessor:
    def test_missing_required_input_raises(self, monkeypatch) -> None:
        async def fake_load(target_id, spec, node_id):
            return _fake_version(
                input_schema=[{"name": "cliente_id", "type": "string", "required": True}],
            )

        monkeypatch.setattr(sub_mod, "_load_version", fake_load)

        proc = CallWorkflowProcessor()
        with pytest.raises(NodeProcessingError, match="cliente_id"):
            proc.process(
                "call",
                {
                    "workflow_id": str(uuid4()),
                    "version": 1,
                    "input_mapping": {},  # nao fornece cliente_id
                },
                {"call_stack": [], "input_data": {}},
            )

    def test_version_pinning_uses_explicit_version(self, monkeypatch) -> None:
        seen_spec: dict[str, Any] = {}

        async def fake_load(target_id, spec, node_id):
            seen_spec["spec"] = spec
            return _fake_version(version=int(spec) if spec != "latest" else 99)

        async def fake_invoke(**kwargs):
            # Pula a parte de connections + run_workflow — foco no spec.
            return {"version": 7, "workflow_output": {}}

        monkeypatch.setattr(sub_mod, "_load_version", fake_load)
        monkeypatch.setattr(sub_mod, "_invoke_subworkflow", fake_invoke)

        proc = CallWorkflowProcessor()
        # Com fake_invoke mockado, proc chama asyncio.run(fake_invoke(...))
        out = proc.process(
            "call",
            {"workflow_id": str(uuid4()), "version": 7, "input_mapping": {}},
            {"call_stack": []},
        )
        assert out["sub_version"] == 7

    def test_output_validation_missing_required(self, monkeypatch) -> None:
        async def fake_load(target_id, spec, node_id):
            return _fake_version(
                output_schema=[
                    {"name": "total", "type": "number", "required": True},
                ],
            )

        # Injeta o run_workflow aninhado para devolver workflow_output vazio.
        async def fake_run_workflow(**kwargs):
            return {
                "status": "completed",
                "node_results": {},
                "node_executions": [],
                "workflow_output": {},  # faltando "total"
            }

        async def fake_resolve(*args, **kwargs):
            return {}

        # Stub connections
        from app.services import connection_service as cs_mod
        monkeypatch.setattr(
            cs_mod.connection_service, "resolve_for_workflow", fake_resolve
        )

        # Stub run_workflow import dentro de _invoke_subworkflow
        import app.orchestration.flows.dynamic_runner as runner_mod
        monkeypatch.setattr(runner_mod, "run_workflow", fake_run_workflow)

        # Evita query ao Workflow para pegar project_id/workspace_id: stub session
        async def fake_execute(self, stmt, *a, **kw):  # type: ignore[no-untyped-def]
            return SimpleNamespace(first=lambda: (None, uuid4()))

        from sqlalchemy.ext.asyncio import AsyncSession
        monkeypatch.setattr(AsyncSession, "execute", fake_execute)

        monkeypatch.setattr(sub_mod, "_load_version", fake_load)

        proc = CallWorkflowProcessor()
        with pytest.raises(NodeProcessingError, match="total"):
            proc.process(
                "call",
                {"workflow_id": str(uuid4()), "version": 1, "input_mapping": {}},
                {"call_stack": []},
            )

    def test_extra_input_not_declared_raises(self, monkeypatch) -> None:
        async def fake_load(target_id, spec, node_id):
            return _fake_version(
                input_schema=[{"name": "x", "type": "string", "required": True}],
            )

        monkeypatch.setattr(sub_mod, "_load_version", fake_load)

        proc = CallWorkflowProcessor()
        with pytest.raises(NodeProcessingError, match="nao declarados"):
            proc.process(
                "call",
                {
                    "workflow_id": str(uuid4()),
                    "version": 1,
                    "input_mapping": {"x": "a", "y": "b"},
                },
                {"call_stack": []},
            )
