"""Pure personalized PageRank helpers for graph recall."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class WeightedEdge:
    """An undirected weighted graph edge used by graph retrieval."""

    source: str
    target: str
    weight: float


def personalized_pagerank(
    edges: Sequence[WeightedEdge],
    teleport: Mapping[str, float],
    *,
    alpha: float,
    max_iterations: int,
    tolerance: float,
) -> dict[str, float]:
    """Return a normalized personalized PageRank distribution.

    Edges are interpreted as undirected because graph retrieval needs both the
    entity-to-document and document-to-entity transition. Dangling-node mass
    returns to the personalized teleport distribution.
    """
    if not 0.0 <= alpha < 1.0:
        raise ValueError("alpha must be in [0, 1)")
    if max_iterations < 0:
        raise ValueError("max_iterations must be non-negative")
    if tolerance <= 0.0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be a positive finite number")

    normalized_teleport = {
        node: float(weight)
        for node, weight in teleport.items()
        if node and math.isfinite(float(weight)) and float(weight) > 0.0
    }
    total_teleport = sum(normalized_teleport.values())
    if total_teleport == 0.0:
        return {}
    normalized_teleport = {
        node: weight / total_teleport for node, weight in normalized_teleport.items()
    }

    adjacency: dict[str, dict[str, float]] = defaultdict(dict)
    for edge in edges:
        if (
            not edge.source
            or not edge.target
            or edge.source == edge.target
            or not math.isfinite(edge.weight)
            or edge.weight <= 0.0
        ):
            continue
        adjacency[edge.source][edge.target] = adjacency[edge.source].get(edge.target, 0.0) + edge.weight
        adjacency[edge.target][edge.source] = adjacency[edge.target].get(edge.source, 0.0) + edge.weight

    nodes = sorted(set(adjacency) | set(normalized_teleport))
    scores = {node: normalized_teleport.get(node, 0.0) for node in nodes}
    outgoing_totals = {node: sum(adjacency[node].values()) for node in nodes}

    for _ in range(max_iterations):
        dangling_mass = sum(scores[node] for node in nodes if outgoing_totals[node] == 0.0)
        updated = {
            node: (1.0 - alpha) * normalized_teleport.get(node, 0.0)
            + alpha * dangling_mass * normalized_teleport.get(node, 0.0)
            for node in nodes
        }
        for source in nodes:
            total = outgoing_totals[source]
            if total == 0.0:
                continue
            for target, weight in adjacency[source].items():
                updated[target] += alpha * scores[source] * weight / total
        delta = sum(abs(updated[node] - scores[node]) for node in nodes)
        scores = updated
        if delta <= tolerance:
            break

    total = sum(scores.values())
    if total == 0.0:
        return {}
    return {node: score / total for node, score in scores.items() if score > 0.0}


def document_scores(
    node_scores: Mapping[str, float],
    node_doc_labels: Mapping[str, str | None],
) -> dict[str, float]:
    """Project graph-node scores to the highest score for each document label."""
    result: dict[str, float] = {}
    for node, score in node_scores.items():
        label = node_doc_labels.get(node)
        if not label or not math.isfinite(score) or score <= 0.0:
            continue
        result[label] = max(result.get(label, 0.0), score)
    return result
