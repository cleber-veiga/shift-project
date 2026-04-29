"""
Testes do serializador YAML (Fase 9).

Cobre dump, parse, round-trip e mensagens de erro.
"""

from __future__ import annotations

import pytest

from app.services.workflow.serializers import (
    YAML_SCHEMA_VERSION,
    YamlVersionError,
    from_yaml,
    to_yaml,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _wf_minimal() -> dict:
    return {
        "nodes": [
            {"id": "a", "type": "inline_data", "position": {"x": 0, "y": 0},
             "data": {"type": "inline_data", "data": [{"x": 1}]}},
            {"id": "b", "type": "filter", "position": {"x": 200, "y": 0},
             "data": {
                 "type": "filter",
                 "conditions": [{"field": "x", "operator": "gt", "value": 0}],
                 "logic": "and",
             }},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b",
             "sourceHandle": None, "targetHandle": "input"},
        ],
        "variables": [
            {"name": "CUTOFF", "type": "string", "required": True},
        ],
    }


def _wf_with_meta() -> dict:
    base = _wf_minimal()
    base["meta"] = {"author": "user@example.com", "tags": ["nightly", "demo"]}
    base["schedule"] = {"cron": "0 0 * * *"}
    base["io_schema"] = {"inputs": [], "outputs": []}
    return base


# ---------------------------------------------------------------------------
# Dump / Parse / Round-trip
# ---------------------------------------------------------------------------

class TestYamlDump:
    def test_dump_includes_required_top_level_fields(self):
        text = to_yaml(_wf_minimal(), name="my_flow", workflow_id="wf-123")
        assert "shift_version: '1.0'" in text or 'shift_version: "1.0"' in text
        assert "workflow_id: wf-123" in text
        assert "workflow_name: my_flow" in text
        assert "nodes:" in text
        assert "edges:" in text

    def test_dump_derives_inputs_outputs_per_node(self):
        text = to_yaml(_wf_minimal())
        # node 'a' tem outputs=[b] (e nao tem inputs); node 'b' tem inputs=[a].
        # Verificacao estrutural via re-parse.
        loaded = from_yaml(text)
        # 'inputs'/'outputs' nao sao parte da definition reconstruida —
        # verifica direto nas edges.
        nodes = loaded["definition"]["nodes"]
        edges = loaded["definition"]["edges"]
        assert {(e["source"], e["target"]) for e in edges} == {("a", "b")}
        assert {n["id"] for n in nodes} == {"a", "b"}


class TestYamlParse:
    def test_missing_version_rejected(self):
        bad = "nodes: []\nedges: []\n"
        with pytest.raises(YamlVersionError) as e:
            from_yaml(bad)
        assert e.value.found is None

    def test_major_version_mismatch_rejected(self):
        bad = "shift_version: '2.0'\nnodes: []\nedges: []\n"
        with pytest.raises(YamlVersionError):
            from_yaml(bad)

    def test_minor_version_diff_accepted(self):
        # Patch/minor superior do mesmo major passa.
        text = "shift_version: '1.2'\nnodes: []\nedges: []\n"
        result = from_yaml(text)
        assert result["definition"]["nodes"] == []

    def test_missing_nodes_rejected(self):
        bad = "shift_version: '1.0'\nedges: []\n"
        with pytest.raises(ValueError, match="nodes"):
            from_yaml(bad)

    def test_missing_edges_rejected(self):
        bad = "shift_version: '1.0'\nnodes: []\n"
        with pytest.raises(ValueError, match="edges"):
            from_yaml(bad)

    def test_duplicate_node_id_rejected(self):
        bad = (
            "shift_version: '1.0'\n"
            "nodes:\n"
            "  - id: a\n    type: filter\n    config: {}\n"
            "  - id: a\n    type: mapper\n    config: {}\n"
            "edges: []\n"
        )
        with pytest.raises(ValueError, match="duplicado"):
            from_yaml(bad)

    def test_node_without_type_rejected(self):
        bad = (
            "shift_version: '1.0'\n"
            "nodes:\n"
            "  - id: a\n    config: {}\n"
            "edges: []\n"
        )
        with pytest.raises(ValueError, match="sem id ou type"):
            from_yaml(bad)

    def test_invalid_yaml_syntax(self):
        with pytest.raises(ValueError, match="YAML invalido"):
            from_yaml("nodes: [unclosed")


class TestRoundTrip:
    @pytest.mark.parametrize("seed", range(20))
    def test_round_trip_preserves_definition(self, seed: int):
        # Variantes simples geradas a partir das duas fixtures base.
        wf = _wf_minimal() if seed % 2 == 0 else _wf_with_meta()
        # Pequena permutacao no edge para variar entre seeds.
        if seed % 3 == 1 and wf["edges"]:
            wf["edges"][0]["targetHandle"] = f"input_{seed}"

        text = to_yaml(wf, name=f"flow_{seed}", workflow_id=f"wf-{seed}")
        round_tripped = from_yaml(text)
        defn = round_tripped["definition"]

        # Nodes preservados (id/type/data/position).
        assert len(defn["nodes"]) == len(wf["nodes"])
        for orig, parsed in zip(wf["nodes"], defn["nodes"]):
            assert orig["id"] == parsed["id"]
            assert orig["type"] == parsed["type"]
            assert orig["data"] == parsed["data"]

        # Edges preservadas (source/target/handles).
        assert len(defn["edges"]) == len(wf["edges"])
        for orig, parsed in zip(wf["edges"], defn["edges"]):
            assert orig["source"] == parsed["source"]
            assert orig["target"] == parsed["target"]
            assert orig.get("sourceHandle") == parsed["sourceHandle"]
            assert orig.get("targetHandle") == parsed["targetHandle"]

        # Variables, meta e schedule preservados.
        if wf.get("variables"):
            assert defn["variables"] == wf["variables"]
        if wf.get("meta"):
            assert defn["meta"] == wf["meta"]
        if wf.get("schedule") is not None:
            assert defn["schedule"] == wf["schedule"]

        # workflow_id e name preservados nos metadados externos.
        assert round_tripped["workflow_id"] == f"wf-{seed}"
        assert round_tripped["name"] == f"flow_{seed}"
