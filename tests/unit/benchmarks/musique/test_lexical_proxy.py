from __future__ import annotations

import pytest

from benchmarks.musique.scripts.lexical_proxy import BM25, analyse, sign_test, weighted_rrf


def test_bm25_ranks_matching_documents_first() -> None:
    bm25 = BM25(
        {
            "a": "Ulrich Walter is a German astronaut",
            "b": "Cologne is a city on the Rhine",
            "c": "the German Aerospace Center is in Cologne",
        }
    )
    assert bm25.top("Where is the German Aerospace Center?", 2) == ["c", "a"]
    assert bm25.top("zzz", 2) == []


def test_weighted_rrf_zero_weight_keeps_first_list_order() -> None:
    assert weighted_rrf([(["a", "b"], 1.0), (["c"], 0.0)])[:2] == ["a", "b"]
    assert weighted_rrf([(["a", "b"], 1.0), (["b"], 1.0)])[0] == "b"


def test_sign_test_symmetric() -> None:
    assert sign_test(0, 0) == 1.0
    assert sign_test(5, 0) == pytest.approx(0.0625)
    assert sign_test(3, 3) == 1.0


def test_analyse_coverage_counts_graph_only_gold() -> None:
    channel = {k: [] for k in ("prod", "prod-novel", "seeds", "seeds-novel", "specific")}
    rows = [
        {
            "qid": "q1",
            "half": "tune",
            "bm25": ["g0"] + [f"x{i}" for i in range(39)],
            **channel,
            "specific-novel": ["g1"],
        },
        {
            "qid": "q2",
            "half": "confirm",
            "bm25": ["g2"] + [f"y{i}" for i in range(39)],
            **channel,
            "specific-novel": ["g3"],
        },
    ]
    gold = {"q1": {"g0", "g1"}, "q2": {"g2", "g3"}}
    last = {"q1": "g1", "q2": "g3"}
    out = analyse(rows, gold, last)
    assert out["coverage"]["bm25@30"]["gold_share"] == 50.0
    assert out["coverage"]["bm25@30+specific-novel"]["gold_share"] == 100.0
    assert out["coverage"]["bm25@30+specific-novel"]["last_hop"] == 2
    assert out["rrf"]["specific-novel"]["chosen_weight"] > 0.0
    assert out["rrf"]["specific-novel"]["confirm_fused_r5"] == 100.0
