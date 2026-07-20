from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from scripts.memory_eval_harness import (
    HarnessRequest,
    LongMemEvalConfig,
    Rag397Config,
    SearchConfig,
    build_search_command,
    run_suites,
    write_report,
)


class FakeRunner:
    def __init__(self, exit_codes: dict[str, int] | None = None) -> None:
        self.exit_codes = exit_codes or {}
        self.calls: list[tuple[Sequence[str], dict[str, str]]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        child_env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, child_env))
        suite = child_env["METRONIX_EVAL_SUITE"]
        output = Path(child_env["METRONIX_EVAL_ARTIFACT"])
        if suite == "search":
            output.write_text(
                json.dumps({"averages": {"mrr": 0.75, "ndcg_at_k": 0.8}}),
                encoding="utf-8",
            )
        elif suite == "rag-397":
            output.write_text(
                json.dumps(
                    {
                        "regression": [{"query": "one"}],
                        "positive": [{"query": "two", "error": "not found"}],
                        "adversarial": [],
                    }
                ),
                encoding="utf-8",
            )
        else:
            output.write_text(
                '{"question_id": "one", "hypothesis": "answer"}\n', encoding="utf-8"
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=self.exit_codes.get(suite, 0),
            stdout="Accuracy: 0.8\n",
            stderr="",
        )


def request_for_all_suites(tmp_path: Path) -> HarnessRequest:
    return HarnessRequest(
        suites=("search", "rag-397", "longmemeval"),
        artifact_dir=tmp_path,
        search=SearchConfig(workspace="MTRNIX", k=10, testset=None, include_unstable=False),
        rag_397=Rag397Config(
            base_url="http://localhost:8000",
            workspace="MTRNIX",
            admin_email="admin@example.com",
            admin_password="not-a-real-password",
        ),
        longmemeval=LongMemEvalConfig(variant="s", max_questions=3, run_judge=True),
    )


def request_with_rag_password(password: str, tmp_path: Path) -> HarnessRequest:
    request = request_for_all_suites(tmp_path)
    return HarnessRequest(
        suites=("rag-397",),
        artifact_dir=request.artifact_dir,
        search=None,
        rag_397=Rag397Config(
            base_url="http://localhost:8000",
            workspace="MTRNIX",
            admin_email="admin@example.com",
            admin_password=password,
        ),
        longmemeval=None,
    )


def test_run_suites_keeps_running_after_a_failure(tmp_path: Path) -> None:
    runner = FakeRunner(exit_codes={"search": 1, "rag-397": 0, "longmemeval": 0})

    report = run_suites(request_for_all_suites(tmp_path), runner)

    assert report.suites["search"].status == "failed"
    assert report.suites["rag-397"].status == "passed"
    assert report.suites["longmemeval"].status == "passed"


def test_build_search_command_uses_explicit_output(tmp_path: Path) -> None:
    config = SearchConfig(workspace="MTRNIX", k=10, testset=None, include_unstable=False)

    assert build_search_command(config, tmp_path / "search.json")[-2:] == [
        "--output",
        str(tmp_path / "search.json"),
    ]


def test_report_never_serializes_secret_values(tmp_path: Path) -> None:
    report = run_suites(request_with_rag_password("super-secret", tmp_path), FakeRunner())

    serialized = json.dumps(report.to_dict())
    assert "super-secret" not in serialized
    assert "METRONIX_ADMIN_PASSWORD" in serialized


def test_report_redacts_inherited_api_keys_from_failure_diagnostics(
    tmp_path: Path, monkeypatch
) -> None:
    class ApiKeyErrorRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="authentication failed for api-key-value",
                stderr="",
    )

    monkeypatch.setenv("EXAMPLE_API_KEY", "api-key-value")
    report = run_suites(
        request_with_rag_password("different-password", tmp_path), ApiKeyErrorRunner()
    )

    assert "api-key-value" not in json.dumps(report.to_dict())


def test_report_summarizes_native_artifacts_without_embedding_them(tmp_path: Path) -> None:
    report = run_suites(request_for_all_suites(tmp_path), FakeRunner())

    assert report.suites["search"].summary == {"mrr": 0.75, "ndcg_at_k": 0.8}
    assert report.suites["rag-397"].summary == {
        "regression_count": 1,
        "positive_count": 1,
        "adversarial_count": 0,
        "error_count": 1,
    }
    assert report.suites["longmemeval"].summary == {"answer_count": 1, "accuracy": 0.8}


def test_unreadable_expected_artifact_fails_the_suite(tmp_path: Path) -> None:
    class MissingArtifactRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    report = run_suites(
        request_with_rag_password("super-secret", tmp_path), MissingArtifactRunner()
    )

    assert report.suites["rag-397"].status == "failed"
    assert "artifact" in (report.suites["rag-397"].error or "").lower()


def test_write_report_writes_sanitized_json(tmp_path: Path) -> None:
    report = run_suites(request_with_rag_password("super-secret", tmp_path), FakeRunner())
    path = tmp_path / "report.json"

    write_report(report, path)

    assert "super-secret" not in path.read_text(encoding="utf-8")
