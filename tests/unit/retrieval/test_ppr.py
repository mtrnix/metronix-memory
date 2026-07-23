from __future__ import annotations

import math
import time

import pytest

from metronix.retrieval.ppr import WeightedEdge, document_scores, personalized_pagerank


def test_ppr_normalizes_scores_for_connected_documents() -> None:
    scores = personalized_pagerank(
        [
            WeightedEdge("entity:auth", "document:auth", 1.0),
            WeightedEdge("entity:auth", "document:billing", 1.0),
        ],
        {"entity:auth": 1.0},
        alpha=0.85,
        max_iterations=100,
        tolerance=1e-9,
    )

    assert scores["document:auth"] == pytest.approx(scores["document:billing"])
    assert sum(scores.values()) == pytest.approx(1.0)


def test_weighted_edge_increases_connected_document_score() -> None:
    scores = personalized_pagerank(
        [
            WeightedEdge("entity:auth", "document:strong", 3.0),
            WeightedEdge("entity:auth", "document:weak", 1.0),
        ],
        {"entity:auth": 1.0},
        alpha=0.85,
        max_iterations=100,
        tolerance=1e-9,
    )

    assert scores["document:strong"] > scores["document:weak"]


def test_dangling_anchor_keeps_mass_in_teleport_distribution() -> None:
    scores = personalized_pagerank(
        [WeightedEdge("entity:connected", "document:guide", 1.0)],
        {"entity:dangling": 1.0},
        alpha=0.85,
        max_iterations=30,
        tolerance=1e-9,
    )

    assert scores == {"entity:dangling": pytest.approx(1.0)}


def test_invalid_edges_and_empty_teleport_return_empty() -> None:
    assert personalized_pagerank(
        [
            WeightedEdge("entity:a", "document:a", 0.0),
            WeightedEdge("entity:a", "document:b", math.nan),
        ],
        {},
        alpha=0.85,
        max_iterations=30,
        tolerance=1e-6,
    ) == {}


def test_document_scores_uses_highest_score_per_label() -> None:
    assert document_scores(
        {"document:one:a": 0.2, "document:one:b": 0.6, "entity:auth": 0.9},
        {"document:one:a": "DOC-1", "document:one:b": "DOC-1", "entity:auth": None},
    ) == {"DOC-1": 0.6}


def test_ppr_on_bounded_graph_completes_within_latency_budget() -> None:
    edges = [
        WeightedEdge(f"entity:{index}", f"entity:{(index + 1) % 500}", 1.0)
        for index in range(500)
    ] + [
        WeightedEdge(f"entity:{index}", f"document:{index}", 1.0)
        for index in range(20)
    ]

    started = time.perf_counter()
    scores = personalized_pagerank(
        edges,
        {"entity:0": 1.0},
        alpha=0.85,
        max_iterations=30,
        tolerance=1e-6,
    )

    assert time.perf_counter() - started < 0.05
    assert sum(scores.values()) == pytest.approx(1.0)
