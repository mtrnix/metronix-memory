from __future__ import annotations

from benchmarks.musique.scripts.ppr_ceiling import rank_excluding, summarize


def test_rank_excluding_skips_anchors_and_breaks_ties_by_label() -> None:
    scores = {"anchor": 0.9, "b": 0.5, "a": 0.5, "c": 0.1}
    assert rank_excluding(scores, "a", {"anchor"}) == 1
    assert rank_excluding(scores, "b", {"anchor"}) == 2
    assert rank_excluding(scores, "c", {"anchor"}) == 3
    assert rank_excluding(scores, "missing", {"anchor"}) is None


def test_summarize_counts_hits_at_k() -> None:
    out = summarize([1, 4, 6, None], [0.1, 0.2, 0.3, 0.4])
    assert out["questions"] == 4
    assert out["in_subgraph"] == 3
    assert (out["next_hop@1"], out["next_hop@5"], out["next_hop@30"]) == (1, 2, 3)
    assert out["latency_median_s"] == 0.25
