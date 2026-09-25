from __future__ import annotations

from benchmarks.musique.scripts.pipeline_probe import (
    GRAPH_MODES,
    aggregate,
    gold_positions,
    score_row,
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
