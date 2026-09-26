from __future__ import annotations

from benchmarks.musique.scripts.pipeline_probe import (
    FUSION_MODES,
    GRAPH_MODES,
    aggregate,
    gold_positions,
    score_row,
    stage_ranks,
)


def _manifest(gold: list[str]) -> dict:
    return {"qid": "q1", "hops": [{"doc_label": g} for g in gold]}


def test_gold_positions_uses_distinct_labels() -> None:
    labels = ["a", "a", "", "b", "c", "b"]
    assert gold_positions(["b", "c", "z"], labels) == {"b": 2, "c": 3, "z": None}


def test_score_row_reads_context_from_fragments() -> None:
    trace = {
        "retrieved_doc_labels": ["x", "g0", "y", "g1"],
        "fragments": [{"doc_label": "g0"}, {"doc_label": "x"}],
        "pipeline_stages": {"recall_graph_count": 3, "recall_total_unique": 31},
    }
    row = score_row(_manifest(["g0", "g1"]), trace)
    assert row["retrieved_rank"] == {"g0": 2, "g1": 4}
    assert row["context_rank"] == {"g0": 1, "g1": None}
    assert (row["context_hop0"], row["context_last_hop"], row["context_both"]) == (
        True,
        False,
        False,
    )
    assert row["context_docs"] == 2
    assert row["recall_graph_count"] == 3


def test_score_row_handles_empty_trace() -> None:
    row = score_row(_manifest(["g0", "g1"]), {})
    assert row["context_both"] is False and row["context_docs"] == 0


def test_aggregate_counts() -> None:
    rows = [
        score_row(
            _manifest(["g0", "g1"]),
            {"retrieved_doc_labels": ["g0", "g1"], "fragments": [{"doc_label": "g0"}]},
        ),
        score_row(
            _manifest(["g0", "g1"]),
            {
                "retrieved_doc_labels": ["a", "b", "c", "d", "e", "g0", "g1"],
                "fragments": [{"doc_label": "g0"}, {"doc_label": "g1"}],
            },
        ),
    ]
    s = aggregate(rows)
    assert s["context_hop0"] == 2 and s["context_last_hop"] == 1 and s["context_both"] == 1
    assert s["retrieved@5_both"] == 1 and s["retrieved@10_both"] == 2
    assert s["retrieved@5_last_hop"] == 1 and s["retrieved@10_last_hop"] == 2


def test_graph_modes_cover_ablation_default_and_ppr() -> None:
    assert GRAPH_MODES["off"] == {} and GRAPH_MODES["bfs"] == {}
    assert GRAPH_MODES["ppr"] == {"METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED": "true"}
    assert GRAPH_MODES["ppr-novel"]["METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS"] == "true"


def test_aggregate_reports_passage_recall_at_k() -> None:
    rows = [
        score_row(_manifest(["g0", "g1"]), {"retrieved_doc_labels": ["g0", "x", "g1"]}),
        score_row(_manifest(["g0", "g1", "g2"]), {"retrieved_doc_labels": ["x", "g2"]}),
    ]
    s = aggregate(rows)
    # q1: 1/2 at k=2, 2/2 at k=5; q2: 1/3 at k=2 and k=5
    assert s["recall@2"] == round(100 * (0.5 + 1 / 3) / 2, 2)
    assert s["recall@5"] == round(100 * (1.0 + 1 / 3) / 2, 2)
    assert s["retrieved@2_hop0"] == 1


def test_stage_ranks_reads_every_stage() -> None:
    rag_trace = {
        "phases": [
            {
                "name": "recall",
                "channels": {
                    "dense": {"candidates": [{"doc_label": "g0"}, {"doc_label": "x"}]},
                    "graph": {"candidates": [{"doc_label": "g1"}]},
                },
            },
            {
                "name": "merge_and_score",
                "candidates": [
                    {"doc_label": "g0", "signal_score": 0.02, "found_by": ["dense"]},
                    {"doc_label": "x", "signal_score": 0.01, "found_by": ["dense"]},
                    {"doc_label": "g1", "signal_score": 0.0, "found_by": ["graph"]},
                ],
            },
        ]
    }
    pool = [("g0", 0.9), ("x", 0.2), ("g1", 0.001)]
    out = stage_ranks(["g0", "g1"], rag_trace, pool)
    assert out["g0"]["dense"] == 1 and out["g0"]["graph"] is None
    assert out["g1"] == {
        "dense": None,
        "graph": 1,
        "found_by": ["graph"],
        "signal_rank": 3,
        "signal_score": 0.0,
        "rerank_rank": 3,
        "rerank_score": 0.001,
    }


def test_fusion_modes_match_the_retrieval_module() -> None:
    from metronix.retrieval.fusion import FUSION_MODES as PRODUCT_MODES

    assert tuple(FUSION_MODES) == tuple(PRODUCT_MODES)
