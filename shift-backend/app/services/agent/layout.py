"""Simple layered auto-layout for build-mode workflow ops.

Computes x/y canvas positions for a list of add_node ops using a BFS-based
topological layer assignment. Edges are specified by source_label/target_label.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

_X_GAP = 270
_Y_GAP = 160
_X_OFFSET = 120
_Y_OFFSET = 120


def compute_layout(
    node_ops: list[dict[str, Any]],
    edge_ops: list[dict[str, Any]],
) -> list[dict[str, float]]:
    """Return [{x, y}] positions in the same order as node_ops.

    Assigns layers by BFS from source nodes. Nodes in the same layer are
    stacked vertically. Disconnected nodes go in their own column.
    """
    if not node_ops:
        return []

    labels = [
        op.get("label") or op.get("node_type") or f"node_{i}"
        for i, op in enumerate(node_ops)
    ]
    label_set = set(labels)

    adj: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = {label: 0 for label in labels}

    for edge_op in edge_ops:
        src = edge_op.get("source_label", "")
        tgt = edge_op.get("target_label", "")
        if src in label_set and tgt in label_set and src != tgt and tgt not in adj[src]:
            adj[src].add(tgt)
            in_degree[tgt] += 1

    # BFS assigns the maximum layer depth to each node (longest-path layering)
    layer: dict[str, int] = {label: 0 for label in labels}
    queue: deque[str] = deque(label for label in labels if in_degree[label] == 0)
    visited: set[str] = set()

    while queue:
        label = queue.popleft()
        if label in visited:
            continue
        visited.add(label)
        for tgt in adj.get(label, set()):
            layer[tgt] = max(layer[tgt], layer[label] + 1)
            in_degree[tgt] -= 1
            if in_degree[tgt] == 0:
                queue.append(tgt)

    # Assign y positions within each layer in declaration order
    layer_counts: dict[int, int] = defaultdict(int)
    positions: list[dict[str, float]] = []

    for label in labels:
        lvl = layer.get(label, 0)
        slot = layer_counts[lvl]
        positions.append(
            {
                "x": float(_X_OFFSET + lvl * _X_GAP),
                "y": float(_Y_OFFSET + slot * _Y_GAP),
            }
        )
        layer_counts[lvl] += 1

    return positions
