"""CLI contracts for evaluation runners that require no live services."""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
import yaml

from scripts import run_eval
from scripts.run_eval import latency_summary

_TESTSET = {
    "queries": [
        {
            "id": "q1",
            "text": "what is the capital of france",
            "expected_doc_labels": ["doc-1"],
        },
        {
            "id": "q2",
            "text": "irrelevant negative probe",
            "expected_doc_labels": [],
        },
    ]
}


@contextmanager
def _noop_telemetry_context(**_kwargs):
    yield


@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    """Redirect eval I/O to a temp dir and stub out the live search call."""
    testset_path = tmp_path / "testset.yaml"
    testset_path.write_text(yaml.safe_dump(_TESTSET), encoding="utf-8")

    results_dir = tmp_path / "eval_results"
    monkeypatch.setattr(run_eval, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(run_eval, "clear_store_cache", lambda: None)
    monkeypatch.setattr(run_eval, "set_telemetry_context", _noop_telemetry_context)

    search_mock = AsyncMock(return_value={"retrieved_doc_labels": ["doc-1"]})
    monkeypatch.setattr(run_eval, "hybrid_search_and_answer", search_mock)

    return testset_path, results_dir


def _run_main(monkeypatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["run_eval.py", *args])
    run_eval.main()


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


def test_locomo_preflight_uses_its_own_configuration_module() -> None:
    completed = subprocess.run(
        [sys.executable, "benchmarks/locomo/scripts/preflight.py", "--check-env-only"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert "workspace: LOCOMO" in completed.stdout
    assert "LOCOMO_CHAT_API_KEY" in completed.stdout
    assert "MABENCH" not in completed.stdout


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


def test_run_eval_writes_output_json_with_computed_metrics(eval_env, monkeypatch, capsys) -> None:
    testset_path, _results_dir = eval_env
    output_path = testset_path.parent / "result.json"

    _run_main(
        monkeypatch,
        ["--testset", str(testset_path), "--output", str(output_path)],
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["averages"]["precision_at_k"] == pytest.approx(1.0)
    assert data["averages"]["negative_accuracy"] == pytest.approx(0.0)
    assert {q["id"] for q in data["per_query"]} == {"q1", "q2"}

    out = capsys.readouterr().out
    assert "POSITIVE" in out
    assert "NEGATIVE" in out


def test_run_eval_save_writes_into_results_dir(eval_env, monkeypatch) -> None:
    testset_path, results_dir = eval_env

    _run_main(monkeypatch, ["--testset", str(testset_path), "--save"])

    saved = list(results_dir.glob("*.json"))
    assert len(saved) == 1
    data = json.loads(saved[0].read_text(encoding="utf-8"))
    assert data["averages"]["precision_at_k"] == pytest.approx(1.0)


def test_run_eval_compare_reports_against_saved_baseline(eval_env, monkeypatch, capsys) -> None:
    testset_path, results_dir = eval_env
    results_dir.mkdir(parents=True, exist_ok=True)
    baseline = {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "workspace": "MTRNIX",
        "k": 10,
        "averages": {
            "precision_at_k": 0.5,
            "recall_at_k": 0.5,
            "mrr": 0.5,
            "ndcg_at_k": 0.5,
            "negative_accuracy": 1.0,
        },
        "latency": {"mean_ms": 1.0, "p50_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0},
        "per_query": [],
    }
    (results_dir / "2026-01-01T00-00-00_00-00.json").write_text(
        json.dumps(baseline), encoding="utf-8"
    )

    _run_main(monkeypatch, ["--testset", str(testset_path), "--compare"])

    out = capsys.readouterr().out
    assert "BEFORE: 2026-01-01T00:00:00+00:00" in out
    assert "P@K" in out
    # Comparing without --save still auto-saves the current run.
    assert len(list(results_dir.glob("*.json"))) == 2


def test_run_eval_compare_without_baseline_prints_hint(eval_env, monkeypatch, capsys) -> None:
    testset_path, results_dir = eval_env

    _run_main(monkeypatch, ["--testset", str(testset_path), "--compare"])

    out = capsys.readouterr().out
    assert "No saved results to compare with" in out
    assert not list(results_dir.glob("*.json"))


def test_run_eval_history_lists_saved_results(eval_env, monkeypatch, capsys) -> None:
    testset_path, results_dir = eval_env
    _run_main(monkeypatch, ["--testset", str(testset_path), "--save"])
    capsys.readouterr()

    _run_main(monkeypatch, ["--history"])

    out = capsys.readouterr().out
    assert "Timestamp" in out
    saved = next(results_dir.glob("*.json"))
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["timestamp"] in out
