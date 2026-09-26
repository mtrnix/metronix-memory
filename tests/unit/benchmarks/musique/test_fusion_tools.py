from __future__ import annotations

import pytest

from benchmarks.musique.scripts.compare_runs import compare, per_question, sign_test
from benchmarks.musique.scripts.fusion_replay import replay, replay_question


def _row(qid: str, gold: list[str], ranks: list[int | None], both: bool = True) -> dict:
    return {
        "qid": qid,
        "gold": gold,
        "retrieved_rank": dict(zip(gold, ranks, strict=True)),
        "context_both": both,
    }


def test_per_question_metrics() -> None:
    row = _row("q", ["g0", "g1", "g2"], [1, 4, None])
    assert per_question(row, "recall@2") == pytest.approx(1 / 3)
    assert per_question(row, "recall@5") == pytest.approx(2 / 3)
    assert per_question(row, "last_hop@5") == 0.0
    assert per_question(row, "both_in_context") == 1.0


def test_sign_test() -> None:
    assert sign_test(0, 0) == 1.0
    assert sign_test(5, 5) == 1.0
    assert sign_test(10, 0) == pytest.approx(2 / 1024)


def test_compare_pairs_by_qid() -> None:
    a = [_row("q1", ["g0", "g1"], [1, None]), _row("q2", ["g0", "g1"], [1, 2])]
    b = [_row("q2", ["g0", "g1"], [1, 2]), _row("q1", ["g0", "g1"], [1, 3])]
    out = compare(a, b, ["recall@5"])
    assert out["questions"] == 2
    assert out["recall@5"]["a"] == 75.0 and out["recall@5"]["b"] == 100.0
    assert (out["recall@5"]["wins"], out["recall@5"]["losses"]) == (1, 0)


def _cand(label: str, ce: float, **scores: float) -> dict:
    return {"doc_label": label, "channel_scores": scores, "signal_score": 0.0, "ce": ce}


def test_replay_rrf_promotes_graph_only_candidate() -> None:
    row = {
        "gold": ["h0", "h1"],
        "candidates": [
            _cand("h0", 0.9, dense=0.03),
            _cand("d1", 0.2, dense=0.02),
            _cand("d2", 0.1, dense=0.01),
            _cand("h1", 0.05, graph=0.5),
        ],
    }
    # h1: 2/61 (graph rank 1, weight 2) + 1/64 (CE rank 4) beats d1: 1/62 + 1/62.
    weights = {"rerank": 1.0, "dense": 1.0, "graph": 2.0}
    top = replay_question(row, "rrf", weights, k=2)
    assert set(top) == {"h0", "h1"}
    assert replay_question(row, "ce", weights, k=2) == ["h0", "d1"]
    summary = replay([row], "rrf", weights, k=2)
    assert summary["recall@2"] == 100.0 and summary["context_both"] == 1
