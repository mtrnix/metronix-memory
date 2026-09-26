from __future__ import annotations

import pytest

from metronix.retrieval.fusion import (
    DEFAULT_WEIGHTS,
    bridge_query,
    calibrated_scores,
    chain_score,
    channel_rankings,
    max_normalize,
    parse_weights,
    pick_anchor,
    ranking_from_scores,
    resolve_mode,
    rrf_scores,
)


def _mr(cid: str, **scores: float) -> dict:
    return {"chunk_id": cid, "channel_scores": dict(scores)}


def test_channel_rankings_orders_each_channel_by_its_own_score() -> None:
    merged = [
        _mr("a", dense=0.03, graph=0.01),
        _mr("b", dense=0.02),
        _mr("c", graph=0.20),
    ]
    ranks = channel_rankings(merged)
    assert ranks["dense"] == {"a": 1, "b": 2}
    assert ranks["graph"] == {"c": 1, "a": 2}


def test_channel_rankings_ties_share_the_best_rank() -> None:
    # BFS graph hits all carry score 1.0: none of them is ranked above another.
    merged = [_mr("a", graph=1.0), _mr("b", graph=1.0), _mr("c", graph=0.5)]
    assert channel_rankings(merged)["graph"] == {"a": 1, "b": 1, "c": 3}


def test_channel_rankings_folds_exact_into_metadata() -> None:
    merged = [_mr("a", exact=1.0), _mr("b", metadata=1.0)]
    ranks = channel_rankings(merged)
    assert set(ranks) == {"metadata"} and ranks["metadata"] == {"a": 1, "b": 1}


def test_ranking_from_scores() -> None:
    assert ranking_from_scores({"a": 0.2, "b": 0.9, "c": 0.2}) == {"b": 1, "a": 2, "c": 2}


def test_rrf_scores_sums_weighted_reciprocal_ranks() -> None:
    ranks = {"dense": {"a": 1, "b": 2}, "graph": {"b": 1}}
    fused = rrf_scores(ranks, {"dense": 1.0, "graph": 2.0}, k=60)
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 2 / 61)


def test_rrf_scores_skips_zero_weight_channels() -> None:
    fused = rrf_scores({"dense": {"a": 1}, "graph": {"b": 1}}, {"dense": 1.0}, k=60)
    assert "b" not in fused


def test_max_normalize() -> None:
    assert max_normalize({"a": 0.5, "b": 0.25, "c": -1.0}) == {"a": 1.0, "b": 0.5, "c": 0.0}
    assert max_normalize({"a": 0.0}) == {"a": 0.0}


def test_calibrated_scores_keeps_rerank_absolute_and_rescales_channels() -> None:
    channel_scores = {
        "rerank": {"a": 0.9, "b": 0.1},
        "dense": {"a": 0.032},
        "graph": {"b": 0.004, "a": 0.002},
    }
    weights = {"rerank": 0.5, "dense": 0.25, "graph": 0.25}
    fused = calibrated_scores(channel_scores, weights, ["a", "b"])
    assert fused["a"] == pytest.approx(0.5 * 0.9 + 0.25 * 1.0 + 0.25 * 0.5)
    assert fused["b"] == pytest.approx(0.5 * 0.1 + 0.25 * 0.0 + 0.25 * 1.0)


def test_calibrated_scores_normalizes_by_active_channels_only() -> None:
    fused = calibrated_scores(
        {"rerank": {"a": 0.8}, "graph": {}}, {"rerank": 0.5, "graph": 0.25}, ["a"]
    )
    assert fused["a"] == pytest.approx(0.8)


def test_pick_anchor_takes_first_anchor_sharing_an_entity() -> None:
    anchors = [("x", {"Ulrich Walter"}), ("y", {"German Aerospace Center", "Cologne"})]
    assert pick_anchor({"German Aerospace Center"}, anchors) == "y"
    assert pick_anchor({"Paris"}, anchors) is None
    assert pick_anchor(set(), anchors) is None


def test_bridge_query_and_chain_score() -> None:
    q = bridge_query("Where is X headquartered?", "  X   works\nfor  Y  ", max_chars=8)
    assert q == "Where is X headquartered?\nX works "
    assert chain_score(0.9, 0.5) == pytest.approx(0.45)
    assert chain_score(-0.1, 0.5) == 0.0


def test_resolve_mode_and_parse_weights() -> None:
    assert resolve_mode("rrf") == "rrf"
    assert resolve_mode("nonsense") == "signal" and resolve_mode(None) == "signal"
    weights = parse_weights("graph=0.5, rerank=2,bad,dense=x", "calibrated")
    assert weights["graph"] == 0.5 and weights["rerank"] == 2.0
    assert weights["dense"] == DEFAULT_WEIGHTS["calibrated"]["dense"]
    assert parse_weights("", "signal") == {}
