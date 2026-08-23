from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from benchmarks.longmemeval.scripts import evaluate_results


def test_main_redacts_judge_key_from_logged_command(monkeypatch, tmp_path: Path, capsys) -> None:
    """The evaluator command log must not disclose the judge credential."""
    secret = "sk-test-judge-secret"
    reference = tmp_path / "longmemeval_s_cleaned.json"
    reference.write_text("[]", encoding="utf-8")
    vendor = tmp_path / "evaluate_qa.py"
    vendor.write_text("", encoding="utf-8")
    run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0))

    monkeypatch.setattr(evaluate_results, "DATA_DIR", tmp_path)
    monkeypatch.setattr(evaluate_results, "VENDOR_EVAL", vendor)
    monkeypatch.setattr(evaluate_results, "load_dotenv", lambda: None)
    monkeypatch.setattr(evaluate_results.subprocess, "run", run)
    monkeypatch.setenv("LME_JUDGE_API_KEY", secret)
    monkeypatch.setenv("LME_JUDGE_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LME_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_results.py", "--results", str(tmp_path / "answers.jsonl"), "--variant", "s"],
    )

    assert evaluate_results.main() == 0

    stdout = capsys.readouterr().out
    assert secret not in stdout
    assert "--judge-api-key <redacted>" in stdout
    command = run.call_args.args[0]
    assert "--judge-api-key" not in command
    assert secret == run.call_args.kwargs["env"]["LME_JUDGE_API_KEY"]
