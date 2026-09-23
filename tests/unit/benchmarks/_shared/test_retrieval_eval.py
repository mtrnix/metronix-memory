from __future__ import annotations

import pytest

from benchmarks._shared import retrieval_eval
from metronix.benchmarker.services.metrics import retrieval as core_retrieval

# ---------------------------------------------------------------------------
# recall_at_k — and parity with the src/ implementation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("retrieved", "expected", "k"),
    [
        (["s0", "s1", "s2"], {"s0", "s2"}, 10),
        (["s0", "s1", "s2"], {"s0", "s2"}, 2),
        (["s3", "s4"], {"s0"}, 10),
        ([], {"s0"}, 5),
        (["s0"], set(), 5),
        (["s0", "s0", "s1"], {"s0", "s1", "s2"}, 10),
        (["s0"], {"s0"}, 0),
    ],
)
def test_recall_matches_core_implementation(
    retrieved: list[str], expected: set[str], k: int
) -> None:
    assert retrieval_eval.recall_at_k(retrieved, expected, k) == core_retrieval.recall_at_k(
        retrieved, expected, k
    )


# ---------------------------------------------------------------------------
# recall_row
# ---------------------------------------------------------------------------


def test_recall_row_computes_all_ks_and_eligibility() -> None:
    row = retrieval_eval.recall_row({"session_1"}, ["session_2", "session_1"], eligible=True)
    assert row["recall_at_10"] == 1.0
    assert row["recall_at_5"] == 1.0
    assert row["oracle_session_tags"] == ["session_1"]
    assert row["retrieved_session_tags"] == ["session_2", "session_1"]
    assert row["recall_gate_eligible"] is True


def test_recall_row_not_eligible_when_abstention() -> None:
    row = retrieval_eval.recall_row({"session_1"}, ["session_1"], eligible=False)
    assert row["recall_gate_eligible"] is False


def test_recall_row_not_eligible_when_no_oracle() -> None:
    row = retrieval_eval.recall_row(set(), ["session_1"], eligible=True)
    assert row["recall_gate_eligible"] is False


def test_recall_row_recall_at_5_slices_first_five() -> None:
    retrieved = [f"session_{i}" for i in range(9)]
    row = retrieval_eval.recall_row({"session_7"}, retrieved, eligible=True)
    assert row["recall_at_10"] == 1.0
    assert row["recall_at_5"] == 0.0


# ---------------------------------------------------------------------------
# aggregate_recall / gate_value
# ---------------------------------------------------------------------------


def _row(rt: str, r10: float, r5: float, *, eligible: bool = True) -> dict:
    return {
        "question_type": rt,
        "recall_at_10": r10,
        "recall_at_5": r5,
        "recall_gate_eligible": eligible,
    }


def test_aggregate_recall_overall_and_by_group() -> None:
    rows = [
        _row("temporal", 1.0, 1.0),
        _row("temporal", 0.0, 0.0),
        _row("multi-session", 1.0, 0.0),
        _row("abs", 0.0, 0.0, eligible=False),  # excluded
    ]
    report = retrieval_eval.aggregate_recall(rows, group_key="question_type")
    assert report["question_count"] == 4
    assert report["eligible_count"] == 3
    assert report["excluded_count"] == 1
    assert report["recall"]["10"] == pytest.approx(2 / 3)
    assert report["recall"]["5"] == pytest.approx(1 / 3)
    assert report["by_group"]["temporal"] == {
        "count": 2,
        "recall": {"10": pytest.approx(0.5), "5": pytest.approx(0.5)},
    }


def test_gate_value_is_recall_at_10() -> None:
    report = retrieval_eval.aggregate_recall([_row("x", 0.8, 0.5)], group_key="question_type")
    assert retrieval_eval.gate_value(report, k=10) == pytest.approx(0.8)
    assert retrieval_eval.gate_value(report, k=5) == pytest.approx(0.5)


def test_gate_value_none_when_nothing_eligible() -> None:
    report = retrieval_eval.aggregate_recall(
        [_row("x", 0.0, 0.0, eligible=False)], group_key="question_type"
    )
    assert report["eligible_count"] == 0
    assert retrieval_eval.gate_value(report, k=10) is None


def test_aggregate_recall_empty() -> None:
    report = retrieval_eval.aggregate_recall([], group_key="category")
    assert report["question_count"] == 0
    assert report["recall"] == {"5": 0.0, "10": 0.0}
    assert report["suspect_count"] == 0
    assert retrieval_eval.gate_value(report) is None


def test_aggregate_recall_counts_suspect_rows() -> None:
    rows = [
        {**_row("x", 1.0, 1.0), "search_suspect": False},
        {**_row("x", 0.0, 0.0), "search_suspect": True},
        {**_row("x", 0.0, 0.0, eligible=False), "search_suspect": True},
        _row("x", 1.0, 1.0),  # no search_suspect key at all
    ]
    report = retrieval_eval.aggregate_recall(rows, group_key="question_type")
    # counted across every row, eligible or not
    assert report["suspect_count"] == 2
