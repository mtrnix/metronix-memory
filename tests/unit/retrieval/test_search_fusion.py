"""Opt-in score-fusion modes wired into search.py (#497)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from metronix.retrieval import search


def _hit(cid: str, label: str, ce: float, text: str = "", title: str = "") -> dict:
    return {"id": cid, "doc_label": label, "rerank_score": ce, "memory": text, "title": title}


def _merged(cid: str, label: str, **scores: float) -> dict:
    return {
        "chunk_id": cid,
        "doc_label": label,
        "memory": {},
        "channels": list(scores),
        "channel_scores": dict(scores),
    }


def _pool() -> tuple[list[dict], list[dict]]:
    reranked = [
        _hit("a", "A", 0.90, "Ulrich Walter joined the German astronaut team.", "Ulrich Walter"),
        _hit("b", "B", 0.05, "Distractor."),
        _hit("c", "C", 0.01, "DLR is headquartered in Cologne.", "German Aerospace Center"),
    ]
    merged = [
        _merged("a", "A", dense=0.032, graph=0.02),
        _merged("b", "B", dense=0.016),
        _merged("c", "C", graph=0.04),
    ]
    return reranked, merged


def test_rrf_mode_ranks_by_reciprocal_ranks() -> None:
    reranked, merged = _pool()
    ranks = search.channel_rankings(merged)
    weights = {"rerank": 1.0, "dense": 1.0, "graph": 1.0}
    with patch.object(search._s, "retrieval_fusion_rrf_k", 60):
        fused = search._fused_scores("rrf", "q", reranked, merged, ranks, weights, "ws")
    # a: CE 1, dense 1, graph 2; b: CE 2, dense 2; c: CE 3, graph 1
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 61 + 1 / 62)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 62)
    assert fused["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert fused["c"] > fused["b"]  # the graph-only candidate is no longer last


def test_calibrated_mode_uses_raw_ce_and_max_normalized_channels() -> None:
    reranked, merged = _pool()
    weights = {"rerank": 0.5, "dense": 0.25, "graph": 0.25}
    fused = search._fused_scores("calibrated", "q", reranked, merged, {}, weights, "ws")
    assert fused["a"] == pytest.approx(0.5 * 0.90 + 0.25 * 1.0 + 0.25 * 0.5)
    assert fused["b"] == pytest.approx(0.5 * 0.05 + 0.25 * 0.5)
    assert fused["c"] == pytest.approx(0.5 * 0.01 + 0.25 * 1.0)


def test_bridge_mode_scores_graph_candidates_against_query_plus_anchor() -> None:
    reranked, merged = _pool()
    entities = {
        "A": {"Ulrich Walter", "German Aerospace Center"},
        "C": {"German Aerospace Center", "Cologne"},
    }
    calls: list[list[tuple[str, str]]] = []

    def fake_score_pairs(pairs):
        calls.append(pairs)
        return [0.8 for _ in pairs]

    with (
        patch.object(search._s, "retrieval_fusion_bridge_anchors", 1),
        patch.object(search._s, "retrieval_fusion_bridge_scope", "graph"),
        patch.object(search, "get_entity_names_by_doc_label", return_value=entities),
        patch("metronix.retrieval.reranker.score_pairs", fake_score_pairs),
    ):
        ce = {r["id"]: r["rerank_score"] for r in reranked}
        out = search._bridge_scores("Where?", reranked, ["a", "b", "c"], ce, merged, "ws")
    # Only "c" is a graph candidate outside the anchors; it is scored once against
    # "question + anchor A" and keeps P(A) * P(c | q + A) = 0.9 * 0.8.
    assert len(calls) == 1 and len(calls[0]) == 1
    query, passage = calls[0][0]
    assert query.startswith("Where?\nUlrich Walter") and passage.startswith("DLR")
    assert out["c"] == pytest.approx(0.72)
    assert out["a"] == 0.90 and out["b"] == 0.05


def test_bridge_mode_leaves_scores_when_no_entity_is_shared() -> None:
    reranked, merged = _pool()
    with (
        patch.object(search._s, "retrieval_fusion_bridge_anchors", 1),
        patch.object(search, "get_entity_names_by_doc_label", return_value={"C": {"Paris"}}),
        patch("metronix.retrieval.reranker.score_pairs") as score_pairs,
    ):
        ce = {r["id"]: r["rerank_score"] for r in reranked}
        out = search._bridge_scores("q", reranked, ["a", "b", "c"], ce, merged, "ws")
    score_pairs.assert_not_called()
    assert out == ce


def test_default_fusion_mode_is_signal() -> None:
    from metronix.core.config import Settings

    assert Settings().retrieval_fusion_mode == "signal"
