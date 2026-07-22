"""CLI contracts for evaluation runners that require no live services."""

from __future__ import annotations

import subprocess
import sys


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
