from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CLI = Path(__file__).resolve().parents[3] / "benchmarks" / "compare_runs.py"


def _run_dir(directory: Path, *, mode: str, recall10: float, dirty: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = "answers.jsonl"
    (directory / name).write_text('{"question_id":"q1","hypothesis":"x"}\n', encoding="utf-8")
    (directory / f"{name}.manifest.json").write_text(
        json.dumps(
            {
                "benchmark": "longmemeval",
                "run_id": f"r-{mode}",
                "repository": {"revision": "a" * 40, "dirty": dirty},
                "dataset": {"sha256": "d" * 64},
                "config": {"top_k": 10, "chat_model": "gpt-4o-mini"},
                "stack": {
                    "mcp_endpoint_identity": "http://localhost:8000/mcp",
                    "operator_declared_retrieval_mode": mode,
                },
            }
        ),
        encoding="utf-8",
    )
    (directory / f"{name}.query_set.json").write_text(
        json.dumps({"question_ids_sha256": "q" * 64}), encoding="utf-8"
    )
    (directory / f"{name}.retrieval.eval.json").write_text(
        json.dumps(
            {
                "eligible_count": 100,
                "recall": {"5": recall10 - 0.1, "10": recall10},
                "latency": {"phases": {"search_ms": {"p50_ms": 200.0, "p95_ms": 350.0}}},
            }
        ),
        encoding="utf-8",
    )
    return directory / name


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CLI), *args], capture_output=True, text=True, check=False
    )


def test_pass_when_comparable_and_gate_met(tmp_path: Path) -> None:
    base = _run_dir(tmp_path / "off", mode="flag-off", recall10=0.70)
    cur = _run_dir(tmp_path / "on", mode="flag-on", recall10=0.75)
    out = tmp_path / "report.json"
    res = _cli(str(base), str(cur), "--gate", "recall_at_10=0.60", "--output", str(out))
    assert res.returncode == 0, res.stderr
    assert "PASS" in res.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["verdict"] == "PASS"
    assert report["metrics"]["recall_at_10"]["delta"] == pytest.approx(0.05)


def test_fail_and_nonzero_exit_on_gate_breach(tmp_path: Path) -> None:
    base = _run_dir(tmp_path / "off", mode="flag-off", recall10=0.70)
    cur = _run_dir(tmp_path / "on", mode="flag-on", recall10=0.50)
    res = _cli(str(base), str(cur), "--gate", "recall_at_10=0.60")
    assert res.returncode == 1
    assert "GATE FAIL" in res.stderr
    assert "FAIL" in res.stdout


def test_fail_on_incompatible_runs(tmp_path: Path) -> None:
    base = _run_dir(tmp_path / "off", mode="flag-off", recall10=0.70)
    cur = _run_dir(tmp_path / "on", mode="flag-on", recall10=0.70, dirty=True)
    res = _cli(str(base), str(cur))
    assert res.returncode == 1
    assert "NOT COMPARABLE" in res.stderr


def test_usage_error_on_unknown_metric(tmp_path: Path) -> None:
    base = _run_dir(tmp_path / "off", mode="flag-off", recall10=0.70)
    cur = _run_dir(tmp_path / "on", mode="flag-on", recall10=0.70)
    res = _cli(str(base), str(cur), "--gate", "mrr=0.5")
    assert res.returncode == 2
    assert "unknown gate metric" in res.stderr
