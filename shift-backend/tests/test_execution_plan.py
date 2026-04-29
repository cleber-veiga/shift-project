"""
Testes para ExecutionPlanSnapshot e build_snapshot.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.orchestration.flows.execution_plan import ExecutionPlanSnapshot, build_snapshot


def _make_node(node_id: str, node_type: str, enabled: bool = True) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "data": {"type": node_type, "enabled": enabled if not enabled else None},
    }


def _make_edge(source: str, target: str) -> dict:
    return {"source": source, "target": target}


class TestBuildSnapshot:

    def test_snapshot_basico(self) -> None:
        nodes = [
            _make_node("n1", "sql_database"),
            _make_node("n2", "filter"),
            _make_node("n3", "loadNode"),
        ]
        edges = [_make_edge("n1", "n2"), _make_edge("n2", "n3")]
        levels = [["n1"], ["n2"], ["n3"]]
        eid = str(uuid4())

        snap = build_snapshot(nodes, edges, levels, eid)

        assert snap.node_count == 3
        assert snap.edge_count == 2
        assert snap.levels == levels
        assert snap.execution_id == UUID(eid)
        assert snap.plan_version == 1

    def test_predicted_strategies_populados(self) -> None:
        nodes = [_make_node("n1", "filter"), _make_node("n2", "join")]
        edges = [_make_edge("n1", "n2")]
        levels = [["n1"], ["n2"]]

        snap = build_snapshot(nodes, edges, levels, str(uuid4()))

        assert "n1" in snap.predicted_strategies
        assert "n2" in snap.predicted_strategies
        assert snap.predicted_strategies["n1"].shape == "narrow"
        assert snap.predicted_strategies["n2"].shape == "wide"
        assert snap.predicted_strategies["n2"].strategy == "data_worker"

    def test_skip_nodes_desabilitados(self) -> None:
        nodes = [
            _make_node("n1", "filter"),
            {"id": "n2", "type": "mapper", "data": {"type": "mapper", "enabled": False}},
        ]
        edges = [_make_edge("n1", "n2")]
        levels = [["n1"], ["n2"]]

        snap = build_snapshot(nodes, edges, levels, str(uuid4()))

        assert "n2" in snap.skip_nodes

    def test_sem_execution_id_gera_uuid(self) -> None:
        snap = build_snapshot([], [], [], None)
        assert isinstance(snap.execution_id, UUID)

    def test_serializa_para_json(self) -> None:
        nodes = [_make_node("n1", "filter")]
        snap = build_snapshot(nodes, [], [["n1"]], str(uuid4()))
        d = snap.model_dump(mode="json")
        assert isinstance(d, dict)
        assert "levels" in d
        assert "predicted_strategies" in d
        assert isinstance(d["execution_id"], str)

    def test_output_node_strategy(self) -> None:
        nodes = [_make_node("n1", "loadNode")]
        snap = build_snapshot(nodes, [], [["n1"]], str(uuid4()))
        pred = snap.predicted_strategies["n1"]
        assert pred.shape == "output"
        assert pred.reason == "output_node"


class TestExecutionPlanSnapshotModel:

    def test_round_trip_pydantic(self) -> None:
        nodes = [_make_node("a", "filter"), _make_node("b", "aggregator")]
        snap = build_snapshot(nodes, [], [["a"], ["b"]], str(uuid4()))
        dumped = snap.model_dump(mode="json")
        restored = ExecutionPlanSnapshot.model_validate(dumped)
        assert restored.node_count == snap.node_count
        assert len(restored.predicted_strategies) == 2
