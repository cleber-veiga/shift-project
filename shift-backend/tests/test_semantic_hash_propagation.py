"""
Verifica que semantic hashes propagam corretamente pelo grafo.

Bug histórico: dynamic_runner passava input_fingerprints=[] sempre, fazendo
todos os nós com mesma config terem o mesmo hash independente do upstream.
Para Fase 5 isso é só observabilidade quebrada; para Fase 6+ que usar o
hash para skip por cache, vira cache poisoning silencioso.

Estes testes simulam a propagação de hashes manualmente (sem rodar o
runner inteiro) seguindo a mesma lógica do bloco corrigido em
dynamic_runner.py.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.workflow.semantic_hash import compute_semantic_hash


def _propagate_hashes(
    nodes: list[tuple[str, str, dict[str, Any]]],
    edges: list[tuple[str, str]],
) -> dict[str, str]:
    """Replica a lógica do dynamic_runner para propagar hashes.

    nodes: lista de (node_id, node_type, config) em ordem topológica.
    edges: lista de (source_id, target_id).
    Retorna: dict de node_id → semantic_hash.
    """
    reverse: dict[str, list[str]] = defaultdict(list)
    for src, tgt in edges:
        reverse[tgt].append(src)

    hashes: dict[str, str] = {}
    for node_id, node_type, config in nodes:
        input_fps = sorted(
            hashes[pred] for pred in reverse.get(node_id, []) if pred in hashes
        )
        hashes[node_id] = compute_semantic_hash(
            config=config,
            input_fingerprints=input_fps,
            node_type=node_type,
        )
    return hashes


class TestPropagationDifferentiatesUpstream:

    def test_same_config_different_upstream_yields_different_hash(self) -> None:
        """A→B→C; mudar config de A muda hash de C, mesmo com B/C iguais."""
        wf_a = _propagate_hashes(
            nodes=[
                ("A",  "filter",      {"conditions": [{"field": "x"}]}),
                ("B",  "mapper",      {"mappings": [{"target": "y"}]}),
                ("C",  "aggregator",  {"group_by": ["y"]}),
            ],
            edges=[("A", "B"), ("B", "C")],
        )
        wf_a_prime = _propagate_hashes(
            nodes=[
                ("A",  "filter",      {"conditions": [{"field": "z"}]}),  # ← diferente
                ("B",  "mapper",      {"mappings": [{"target": "y"}]}),   # igual
                ("C",  "aggregator",  {"group_by": ["y"]}),               # igual
            ],
            edges=[("A", "B"), ("B", "C")],
        )
        assert wf_a["B"] != wf_a_prime["B"], "B deveria diferir (upstream A diff)"
        assert wf_a["C"] != wf_a_prime["C"], (
            "C deveria diferir mesmo com config igual — upstream chain mudou"
        )

    def test_two_upstreams_different_order_same_hash(self) -> None:
        """Join com left/right invertidos → mesmo hash (sorted internally)."""
        wf1 = _propagate_hashes(
            nodes=[
                ("L", "filter", {"conditions": [{"field": "id"}]}),
                ("R", "filter", {"conditions": [{"field": "name"}]}),
                ("J", "join",   {"on": "id"}),
            ],
            edges=[("L", "J"), ("R", "J")],
        )
        wf2 = _propagate_hashes(
            nodes=[
                # Mesma config, mas adiciona R antes de L na ordem topológica.
                ("R", "filter", {"conditions": [{"field": "name"}]}),
                ("L", "filter", {"conditions": [{"field": "id"}]}),
                ("J", "join",   {"on": "id"}),
            ],
            edges=[("L", "J"), ("R", "J")],
        )
        assert wf1["J"] == wf2["J"], (
            "Hash de J deveria ser idêntico — input_fingerprints é sorted"
        )


class TestStability:

    def test_100_runs_identical_yield_one_hash_per_node(self) -> None:
        """Critério §5.2: 100 runs idênticas → 1 hash distinto por nó."""
        nodes = [
            ("A", "filter",     {"conditions": [{"field": "x"}]}),
            ("B", "mapper",     {"mappings": [{"source": "x", "target": "y"}]}),
            ("C", "aggregator", {"group_by": ["y"]}),
        ]
        edges = [("A", "B"), ("B", "C")]

        hashes_per_run = [_propagate_hashes(nodes, edges) for _ in range(100)]

        for nid in ("A", "B", "C"):
            distinct = {h[nid] for h in hashes_per_run}
            assert len(distinct) == 1, (
                f"Nó {nid} produziu {len(distinct)} hashes distintos em 100 runs idênticas"
            )


class TestUpstreamMissingDoesNotCrash:

    def test_upstream_not_in_hashes_dict_skipped_gracefully(self) -> None:
        """Se um predecessor ainda não foi processado, ignora sem crash."""
        # B referencia upstream "A" que não está em hashes — deve só usar [].
        reverse = {"B": ["A"]}
        hashes: dict[str, str] = {}
        input_fps = sorted(
            hashes[pred] for pred in reverse.get("B", []) if pred in hashes
        )
        h = compute_semantic_hash(
            config={"x": 1}, input_fingerprints=input_fps, node_type="filter"
        )
        assert isinstance(h, str)
        assert len(h) == 32
