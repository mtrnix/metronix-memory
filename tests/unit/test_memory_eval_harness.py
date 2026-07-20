from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.memory_eval_harness import (
    HarnessReport,
    HarnessRequest,
    LongMemEvalConfig,
    Rag397Config,
    Regression,
    SearchConfig,
    SuiteResult,
    attach_baseline_comparison,
    build_longmemeval_command,
    build_search_command,
    compare_baseline,
    parse_threshold,
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
                        "positive": [{"query": "two"}],
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


def suite_configuration(suite: str) -> dict[str, object]:
    if suite == "search":
        return {
            "workspace": "MTRNIX",
            "k": 10,
            "testset": None,
            "include_unstable": False,
        }
    if suite == "rag-397":
        return {
            "base_url": "http://localhost:8000",
            "workspace": "MTRNIX",
            "credential_environment_variables": [
                "METRONIX_ADMIN_EMAIL",
                "METRONIX_ADMIN_PASSWORD",
            ],
        }
    return {"variant": "s", "max_questions": 3, "run_judge": True}


def report_with_summary(
    suite: str,
    summary: dict[str, float | None],
    *,
    status: str = "passed",
    configuration: dict[str, object] | None = None,
) -> HarnessReport:
    return HarnessReport(
        schema_version=1,
        started_at="2026-07-20T00:00:00+00:00",
        finished_at="2026-07-20T00:00:01+00:00",
        requested_suites=[suite],
        suites={
            suite: SuiteResult(
                status=status,  # type: ignore[arg-type]
                started_at="2026-07-20T00:00:00+00:00",
                finished_at="2026-07-20T00:00:01+00:00",
                duration_seconds=1.0,
                exit_code=0,
                configuration=configuration or suite_configuration(suite),
                artifacts={},
                summary=summary,
            )
        },
        regressions=[],
    )


def current_search_mrr(mrr: float) -> HarnessReport:
    return report_with_summary("search", {"mrr": mrr})


def baseline_search_mrr(mrr: float) -> HarnessReport:
    return report_with_summary("search", {"mrr": mrr})


def baseline_with_accuracy() -> HarnessReport:
    return report_with_summary("longmemeval", {"accuracy": 0.8})


def current_without(metric: str) -> HarnessReport:
    suite, _ = metric.split(".", maxsplit=1)
    return report_with_summary(suite, {})


def test_threshold_breach_marks_run_failed() -> None:
    regressions = compare_baseline(
        current_search_mrr(0.70), baseline_search_mrr(0.80), {"search.mrr": 0.05}
    )

    assert regressions == [Regression(metric="search.mrr", delta=-0.10, threshold=0.05)]


def test_threshold_breach_uses_unrounded_delta() -> None:
    regressions = compare_baseline(
        current_search_mrr(0.749999999999),
        baseline_search_mrr(0.80),
        {"search.mrr": 0.05},
    )

    assert len(regressions) == 1
    assert regressions[0].metric == "search.mrr"
    assert regressions[0].delta < -0.05
    assert regressions[0].threshold == 0.05


def test_threshold_breach_is_not_lost_to_report_display_rounding() -> None:
    regressions = compare_baseline(
        current_search_mrr(0.7499999999999),
        baseline_search_mrr(0.80),
        {"search.mrr": 0.05},
    )

    assert regressions == [
        Regression(metric="search.mrr", delta=-0.05, threshold=0.05)
    ]


def test_incompatible_or_missing_metric_is_informational() -> None:
    assert compare_baseline(
        current_without("longmemeval.accuracy"), baseline_with_accuracy(), {}
    ) == []


def test_comparison_attaches_same_key_deltas_to_report() -> None:
    report = attach_baseline_comparison(
        current_search_mrr(0.75), baseline_search_mrr(0.80), {"search.mrr": 0.10}
    )

    assert report.deltas == {"search.mrr": -0.05}
    assert report.regressions == []


def test_comparison_is_incompatible_when_suite_status_is_not_passed() -> None:
    baseline = report_with_summary("search", {"mrr": 0.8}, status="failed")

    report = attach_baseline_comparison(
        current_search_mrr(0.7), baseline, {"search.mrr": 0.05}
    )

    assert report.deltas == {}
    assert report.regressions == []
    assert report.incompatible_suites == {
        "search": "current and baseline suite status must both be passed"
    }


def test_comparison_is_incompatible_when_normalized_configuration_differs() -> None:
    baseline = report_with_summary(
        "search",
        {"mrr": 0.8},
        configuration={
            "include_unstable": False,
            "testset": None,
            "k": 20,
            "workspace": "MTRNIX",
        },
    )

    report = attach_baseline_comparison(
        current_search_mrr(0.7), baseline, {"search.mrr": 0.05}
    )

    assert report.deltas == {}
    assert report.regressions == []
    assert report.incompatible_suites == {
        "search": "current and baseline suite configuration must be identical"
    }


def test_parse_threshold_rejects_unknown_or_invalid_quality_gates() -> None:
    assert parse_threshold("search.mrr=0.05") == ("search.mrr", 0.05)

    for value in ("search.mrr", "search.mrr=-0.01", "search.mrr=not-a-number"):
        try:
            parse_threshold(value)
        except ValueError as exc:
            assert str(exc) == "threshold must be suite.metric=non-negative-number"
        else:
            raise AssertionError(f"expected {value!r} to be rejected")


def test_parse_threshold_rejects_unknown_metric_before_evaluation() -> None:
    try:
        parse_threshold("rag-397.error_count=1.0")
    except ValueError as exc:
        assert str(exc) == "unknown threshold metric: rag-397.error_count"
    else:
        raise AssertionError("expected RAG-397 trace counter threshold to be rejected")


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


def test_run_suites_uses_real_runner_output_flags_with_absolute_paths(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    request = replace(request_for_all_suites(tmp_path), artifact_dir=Path("artifacts"))
    runner = FakeRunner()

    run_suites(request, runner)

    search_command, longmemeval_command = runner.calls[0][0], runner.calls[2][0]
    expected_search_output = str(tmp_path / "artifacts" / "search.json")
    expected_longmemeval_output = str(tmp_path / "artifacts" / "longmemeval.jsonl")
    assert search_command[:2] == [sys.executable, "scripts/run_eval.py"]
    assert search_command[-2:] == ["--output", expected_search_output]
    assert longmemeval_command[:2] == ["bash", "benchmarks/longmemeval/run.sh"]
    longmemeval_output_index = longmemeval_command.index("--output") + 1
    assert longmemeval_command[longmemeval_output_index] == expected_longmemeval_output
    assert "--force" in longmemeval_command


def test_longmemeval_command_forces_fresh_explicit_artifact(tmp_path: Path) -> None:
    command = build_longmemeval_command(
        LongMemEvalConfig(variant="s", max_questions=None, run_judge=False),
        tmp_path / "longmemeval.jsonl",
    )

    assert command.count("--force") == 1


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


def test_report_does_not_persist_any_raw_child_output(tmp_path: Path) -> None:
    class SensitiveOutputRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=23,
                stdout="raw model answer that must not be retained",
                stderr="secret loaded by child dotenv",
            )

    report = run_suites(
        request_with_rag_password("different-password", tmp_path), SensitiveOutputRunner()
    )
    serialized = json.dumps(report.to_dict())

    assert "raw model answer" not in serialized
    assert "secret loaded by child dotenv" not in serialized
    assert (report.suites["rag-397"].error or "").startswith(
        "Suite command exited with code 23"
    )


def test_report_summarizes_native_artifacts_without_embedding_them(tmp_path: Path) -> None:
    report = run_suites(request_for_all_suites(tmp_path), FakeRunner())

    assert report.suites["search"].summary == {"mrr": 0.75, "ndcg_at_k": 0.8}
    assert report.suites["rag-397"].summary == {
        "regression_count": 1,
        "positive_count": 1,
        "adversarial_count": 0,
        "error_count": 0,
    }
    assert report.suites["longmemeval"].summary == {
        "answer_count": 1,
        "error_count": 0,
        "accuracy": 0.8,
    }


def test_rag_case_error_fails_suite_even_when_runner_exits_zero(tmp_path: Path) -> None:
    class RagCaseErrorRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            if child_env["METRONIX_EVAL_SUITE"] != "rag-397":
                return super().run(command, child_env=child_env)
            output = Path(child_env["METRONIX_EVAL_ARTIFACT"])
            output.write_text(
                json.dumps(
                    {
                        "regression": [{"query": "one", "error": "request failed"}],
                        "positive": [],
                        "adversarial": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                args=command, returncode=0, stdout="", stderr=""
            )

    report = run_suites(request_for_all_suites(tmp_path), RagCaseErrorRunner())

    assert report.suites["rag-397"].status == "failed"
    assert report.suites["rag-397"].summary["error_count"] == 1


def test_longmemeval_error_hypothesis_fails_suite_even_when_runner_exits_zero(
    tmp_path: Path,
) -> None:
    class ErrorHypothesisRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            output = Path(child_env["METRONIX_EVAL_ARTIFACT"])
            output.write_text(
                '{"question_id": "one", "hypothesis": "Error: provider unavailable"}\n',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                args=command, returncode=0, stdout="Accuracy: 0.8", stderr=""
            )

    request = replace(request_for_all_suites(tmp_path), suites=("longmemeval",))
    report = run_suites(request, ErrorHypothesisRunner())

    assert report.suites["longmemeval"].status == "failed"
    assert report.suites["longmemeval"].summary["error_count"] == 1


@pytest.mark.parametrize("judge_output", ["Accuracy: not-a-number", "Accuracy: 1e309"])
def test_judged_longmemeval_requires_finite_parsed_accuracy(
    tmp_path: Path, judge_output: str
) -> None:
    class MissingAccuracyRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            output = Path(child_env["METRONIX_EVAL_ARTIFACT"])
            output.write_text(
                '{"question_id": "one", "hypothesis": "answer"}\n', encoding="utf-8"
            )
            return subprocess.CompletedProcess(
                args=command, returncode=0, stdout=judge_output, stderr=""
            )

    request = replace(request_for_all_suites(tmp_path), suites=("longmemeval",))
    report = run_suites(request, MissingAccuracyRunner())

    assert report.suites["longmemeval"].status == "failed"
    assert report.suites["longmemeval"].summary["accuracy"] is None


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
