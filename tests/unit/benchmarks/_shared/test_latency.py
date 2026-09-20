from __future__ import annotations

import random

import pytest

from benchmarks._shared import latency
from scripts.run_eval import latency_summary


def test_summarize_basic() -> None:
    out = latency.summarize([10, 20, 30, 40])
    assert out["mean_ms"] == pytest.approx(25.0)
    assert out["max_ms"] == 40.0
    assert out["p50_ms"] == pytest.approx(25.0)  # linear interp between 20 and 30


def test_summarize_single_value() -> None:
    assert latency.summarize([7.5]) == {
        "mean_ms": 7.5,
        "p50_ms": 7.5,
        "p95_ms": 7.5,
        "max_ms": 7.5,
    }


def test_summarize_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one measurement"):
        latency.summarize([])


@pytest.mark.parametrize("seed", range(5))
def test_summarize_matches_run_eval_latency_summary(seed: int) -> None:
    rng = random.Random(seed)
    values = [rng.uniform(1, 5000) for _ in range(rng.randint(1, 200))]
    assert latency.summarize(values) == latency_summary(values)


def test_aggregate_latency_per_phase() -> None:
    rows = [
        {"ingest_ms": 100, "search_ms": 50, "answer_ms": 800, "total_ms": 960},
        {"ingest_ms": 120, "search_ms": 70, "answer_ms": 900, "total_ms": 1100},
        {"hypothesis": "Error: x"},  # no timing — skipped per phase
    ]
    report = latency.aggregate_latency(rows)
    assert report["count"] == 3
    assert report["phases"]["search_ms"]["n"] == 2
    assert report["phases"]["search_ms"]["p50_ms"] == pytest.approx(60.0)
    assert report["phases"]["answer_ms"]["n"] == 2
    assert "total_ms" in report["phases"]


def test_aggregate_latency_no_rows_with_timing() -> None:
    report = latency.aggregate_latency([{"hypothesis": "Error"}])
    assert report["phases"] == {}
