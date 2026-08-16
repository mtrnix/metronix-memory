"""CLI contracts for evaluation runners that require no live services."""

from __future__ import annotations

import subprocess
import sys

import pytest

from scripts.run_eval import latency_summary


def test_search_eval_help_lists_output_flag() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_eval.py", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0
    assert "--output" in completed.stdout


def test_longmemeval_help_lists_output_flag() -> None:
    completed = subprocess.run(
        ["bash", "benchmarks/longmemeval/run.sh", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0
    assert "--output" in completed.stdout


def test_latency_summary_reports_distribution_in_milliseconds() -> None:
    assert latency_summary([10.0, 20.0, 30.0, 40.0]) == {
        "mean_ms": pytest.approx(25.0),
        "p50_ms": pytest.approx(25.0),
        "p95_ms": pytest.approx(38.5),
        "max_ms": pytest.approx(40.0),
    }


def test_latency_summary_rejects_empty_measurements() -> None:
    with pytest.raises(ValueError, match="at least one"):
        latency_summary([])
