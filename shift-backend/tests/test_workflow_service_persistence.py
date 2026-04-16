"""
Testes do mapeamento evento-do-runner -> ``WorkflowNodeExecution``.

Garante que o helper estatico ``_build_node_execution_record`` preserva
os campos importantes e e blindado contra eventos malformados — sem
bloquear o commit da ``WorkflowExecution`` principal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.services.workflow_service import WorkflowExecutionService


class TestBuildNodeExecutionRecord:
    def test_full_event_mapped_to_all_fields(self) -> None:
        exec_id = uuid4()
        started = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2025, 1, 1, 12, 0, 3, tzinfo=timezone.utc)
        evt = {
            "node_id": "n1",
            "node_type": "bulk_insert",
            "label": "Inserir Pessoas",
            "status": "success",
            "duration_ms": 3500,
            "row_count_in": 100,
            "row_count_out": 98,
            "output_summary": {"rows_written": 98, "target_table": "t"},
            "error_message": None,
            "started_at": started,
            "completed_at": completed,
        }
        rec = WorkflowExecutionService._build_node_execution_record(exec_id, evt)

        assert rec.execution_id == exec_id
        assert rec.node_id == "n1"
        assert rec.node_type == "bulk_insert"
        assert rec.label == "Inserir Pessoas"
        assert rec.status == "success"
        assert rec.duration_ms == 3500
        assert rec.row_count_in == 100
        assert rec.row_count_out == 98
        assert rec.output_summary == {"rows_written": 98, "target_table": "t"}
        assert rec.error_message is None
        assert rec.started_at == started
        assert rec.completed_at == completed

    def test_error_event_carries_error_message(self) -> None:
        evt = {
            "node_id": "n2",
            "node_type": "sql_database",
            "label": "Consulta",
            "status": "error",
            "duration_ms": 120,
            "error_message": "ORA-00942: table or view does not exist",
        }
        rec = WorkflowExecutionService._build_node_execution_record(uuid4(), evt)
        assert rec.status == "error"
        assert "ORA-00942" in rec.error_message

    def test_skipped_by_branch_event(self) -> None:
        evt = {
            "node_id": "n3",
            "node_type": "bulk_insert",
            "label": "Insert",
            "status": "skipped",
            "duration_ms": 0,
            "output_summary": {"reason": "skipped_by_branch"},
        }
        rec = WorkflowExecutionService._build_node_execution_record(uuid4(), evt)
        assert rec.status == "skipped"
        assert rec.duration_ms == 0
        assert rec.output_summary == {"reason": "skipped_by_branch"}

    def test_malformed_event_does_not_crash(self) -> None:
        """Campos faltantes caem em valores default seguros."""
        evt: dict = {}  # totalmente vazio
        rec = WorkflowExecutionService._build_node_execution_record(uuid4(), evt)
        assert rec.node_id == ""
        assert rec.node_type == "unknown"
        assert rec.status == "success"  # default conservador
        assert rec.duration_ms == 0
        assert rec.row_count_in is None
        assert rec.row_count_out is None
        assert rec.output_summary is None

    def test_row_counts_reject_non_ints(self) -> None:
        """Valores estranhos em row_count_* viram None em vez de quebrar."""
        evt = {
            "node_id": "n",
            "node_type": "mapper",
            "status": "success",
            "row_count_in": "100",        # string
            "row_count_out": True,          # bool — descartar mesmo sendo int
        }
        rec = WorkflowExecutionService._build_node_execution_record(uuid4(), evt)
        assert rec.row_count_in is None
        assert rec.row_count_out is None

    def test_output_summary_not_dict_becomes_none(self) -> None:
        evt = {
            "node_id": "n",
            "node_type": "x",
            "status": "success",
            "output_summary": "not-a-dict",
        }
        rec = WorkflowExecutionService._build_node_execution_record(uuid4(), evt)
        assert rec.output_summary is None
