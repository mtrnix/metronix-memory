from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import memory_eval_harness as harness
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
            output.write_text('{"question_id": "one", "hypothesis": "answer"}\n', encoding="utf-8")
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
    return {
        "variant": "s",
        "max_questions": 3,
        "run_judge": True,
        "metronix_mcp_endpoint": "http://localhost:8000/mcp",
        "workspace": "MABENCH",
        "top_k": 10,
        "chat_model": "gpt-4o-mini",
        "chat_base_url": "https://api.openai.com/v1",
        "judge_model": "gpt-4o",
        "judge_base_url": "https://api.openai.com/v1",
        "dataset": {
            "filename": "longmemeval_s_cleaned.json",
            "source": (
                "https://huggingface.co/datasets/xiaowu0162/"
                "longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json"
            ),
            "sha256": None,
        },
    }


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

    assert regressions == [Regression(metric="search.mrr", delta=-0.05, threshold=0.05)]


def test_incompatible_or_missing_metric_is_informational() -> None:
    assert (
        compare_baseline(current_without("longmemeval.accuracy"), baseline_with_accuracy(), {})
        == []
    )


def test_comparison_attaches_same_key_deltas_to_report() -> None:
    report = attach_baseline_comparison(
        current_search_mrr(0.75), baseline_search_mrr(0.80), {"search.mrr": 0.10}
    )

    assert report.deltas == {"search.mrr": -0.05}
    assert report.regressions == []


def test_comparison_is_incompatible_when_suite_status_is_not_passed() -> None:
    baseline = report_with_summary("search", {"mrr": 0.8}, status="failed")

    report = attach_baseline_comparison(current_search_mrr(0.7), baseline, {"search.mrr": 0.05})

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

    report = attach_baseline_comparison(current_search_mrr(0.7), baseline, {"search.mrr": 0.05})

    assert report.deltas == {}
    assert report.regressions == []
    assert report.incompatible_suites == {
        "search": "current and baseline suite configuration must be identical"
    }


@pytest.mark.parametrize(
    ("key", "different_value"),
    [
        ("workspace", "OTHER"),
        ("metronix_mcp_endpoint", "https://other.example/mcp"),
        ("top_k", 20),
        ("chat_model", "different-chat"),
        ("chat_base_url", "https://chat.example/v1"),
        ("judge_model", "different-judge"),
        ("judge_base_url", "https://judge.example/v1"),
        (
            "dataset",
            {
                "filename": "longmemeval_s_cleaned.json",
                "source": "https://example.invalid/different-dataset.json",
                "sha256": "abc123",
            },
        ),
    ],
)
def test_longmemeval_comparison_includes_effective_result_configuration(
    key: str, different_value: object
) -> None:
    current = report_with_summary("longmemeval", {"accuracy": 0.7})
    baseline_configuration = suite_configuration("longmemeval")
    baseline_configuration[key] = different_value
    baseline = report_with_summary(
        "longmemeval", {"accuracy": 0.8}, configuration=baseline_configuration
    )

    report = attach_baseline_comparison(current, baseline, {"longmemeval.accuracy": 0.05})

    assert report.deltas == {}
    assert report.regressions == []
    assert report.incompatible_suites == {
        "longmemeval": "current and baseline suite configuration must be identical"
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


def test_longmemeval_records_effective_non_secret_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LME_WORKSPACE_ID", "ENV-WORKSPACE")
    monkeypatch.setenv("LME_RETRIEVE_TOP_K", "17")
    monkeypatch.setenv("LME_CHAT_MODEL", "chat-model")
    monkeypatch.setenv("LME_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("LME_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("LME_JUDGE_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv(
        "METRONIX_MCP_URL",
        "HTTPS://user:password@Metronix.Example:443/mcp/?token=secret#credentials",
    )
    monkeypatch.setenv("LME_CHAT_API_KEY", "must-not-be-reported")
    request = replace(request_for_all_suites(tmp_path), suites=("longmemeval",))

    report = run_suites(request, FakeRunner())

    configuration = report.suites["longmemeval"].configuration
    assert configuration["metronix_mcp_endpoint"] == "https://metronix.example/mcp"
    assert configuration["workspace"] == "ENV-WORKSPACE"
    assert configuration["top_k"] == 17
    assert configuration["chat_model"] == "chat-model"
    assert configuration["chat_base_url"] == "https://chat.example/v1"
    assert configuration["judge_model"] == "judge-model"
    assert configuration["judge_base_url"] == "https://judge.example/v1"
    assert configuration["dataset"] == {
        "filename": "longmemeval_s_cleaned.json",
        "source": (
            "https://huggingface.co/datasets/xiaowu0162/"
            "longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json"
        ),
        "sha256": None,
    }
    assert "must-not-be-reported" not in json.dumps(configuration)
    assert "password" not in json.dumps(configuration)
    assert "secret" not in json.dumps(configuration)


def test_longmemeval_malformed_effective_environment_fails_without_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LME_RETRIEVE_TOP_K", "not-an-integer")
    request = replace(request_for_all_suites(tmp_path), suites=("longmemeval",))
    runner = FakeRunner()

    report = run_suites(request, runner)

    assert report.suites["longmemeval"].status == "failed"
    assert report.suites["longmemeval"].error == "Could not prepare suite configuration"
    assert runner.calls == []


def test_longmemeval_dataset_preparation_failure_does_not_abort_later_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_hash(_: Path) -> str | None:
        raise OSError("offline dataset read failed")

    monkeypatch.setattr(harness, "_sha256_if_present", fail_hash)
    request = replace(
        request_for_all_suites(tmp_path),
        suites=("longmemeval", "search"),
        rag_397=None,
    )
    runner = FakeRunner()

    report = run_suites(request, runner)

    assert report.suites["longmemeval"].status == "failed"
    assert report.suites["search"].status == "passed"
    assert [call[1]["METRONIX_EVAL_SUITE"] for call in runner.calls] == ["search"]


def test_longmemeval_effective_configuration_honors_benchmark_env_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark_root = tmp_path / "benchmarks" / "longmemeval"
    benchmark_root.mkdir(parents=True)
    benchmark_env = benchmark_root / ".env.benchmark"
    benchmark_env.write_text(
        "\n".join(
            [
                "LME_WORKSPACE_ID=FILE-WORKSPACE",
                "LME_RETRIEVE_TOP_K=23",
                "LME_CHAT_MODEL=file-chat",
                "LME_CHAT_BASE_URL=https://file-chat.example/v1",
                "LME_JUDGE_MODEL=file-judge",
                "LME_JUDGE_BASE_URL=https://file-judge.example/v1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LME_WORKSPACE_ID", "PROCESS-WORKSPACE")
    monkeypatch.setenv("LME_RETRIEVE_TOP_K", "5")
    monkeypatch.setattr(harness, "_LONGMEMEVAL_ROOT", benchmark_root)
    monkeypatch.setattr(harness, "_LONGMEMEVAL_ENV", benchmark_env)
    monkeypatch.setattr(harness, "_LONGMEMEVAL_LEGACY_ENV", benchmark_root / ".env")
    request = replace(request_for_all_suites(tmp_path / "artifacts"), suites=("longmemeval",))

    report = run_suites(request, FakeRunner())

    configuration = report.suites["longmemeval"].configuration
    assert configuration["workspace"] == "FILE-WORKSPACE"
    assert configuration["top_k"] == 23
    assert configuration["chat_model"] == "file-chat"
    assert configuration["chat_base_url"] == "https://file-chat.example/v1"
    assert configuration["judge_model"] == "file-judge"
    assert configuration["judge_base_url"] == "https://file-judge.example/v1"


def test_longmemeval_records_local_dataset_content_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark_root = tmp_path / "benchmarks" / "longmemeval"
    dataset = benchmark_root / "data" / "longmemeval_s_cleaned.json"
    dataset.parent.mkdir(parents=True)
    dataset_bytes = b"dataset-version"
    dataset.write_bytes(dataset_bytes)
    monkeypatch.setattr(harness, "_LONGMEMEVAL_ROOT", benchmark_root)
    monkeypatch.setattr(harness, "_LONGMEMEVAL_ENV", benchmark_root / ".env.benchmark")
    monkeypatch.setattr(harness, "_LONGMEMEVAL_LEGACY_ENV", benchmark_root / ".env")
    request = replace(request_for_all_suites(tmp_path / "artifacts"), suites=("longmemeval",))

    report = run_suites(request, FakeRunner())

    dataset_configuration = report.suites["longmemeval"].configuration["dataset"]
    assert isinstance(dataset_configuration, dict)
    assert dataset_configuration["sha256"] == hashlib.sha256(dataset_bytes).hexdigest()


def test_longmemeval_removes_stale_artifact_before_process_launch(tmp_path: Path) -> None:
    artifact = tmp_path / "longmemeval.jsonl"
    artifact.write_text('{"question_id":"stale"}\n', encoding="utf-8")

    class PreflightFailureRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            assert not artifact.exists()
            return subprocess.CompletedProcess(
                args=command, returncode=1, stdout="preflight failed", stderr=""
            )

    request = replace(request_for_all_suites(tmp_path), suites=("longmemeval",))
    report = run_suites(request, PreflightFailureRunner())

    assert report.suites["longmemeval"].status == "failed"
    assert not artifact.exists()


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
    assert (report.suites["rag-397"].error or "").startswith("Suite command exited with code 23")


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
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    report = run_suites(request_for_all_suites(tmp_path), RagCaseErrorRunner())

    assert report.suites["rag-397"].status == "failed"
    assert report.suites["rag-397"].summary["error_count"] == 1


@pytest.mark.parametrize("error_value", ["", None, False])
def test_rag_case_error_counts_key_presence(tmp_path: Path, error_value: object) -> None:
    class RagCaseErrorRunner(FakeRunner):
        def run(
            self,
            command: Sequence[str],
            *,
            child_env: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            output = Path(child_env["METRONIX_EVAL_ARTIFACT"])
            output.write_text(
                json.dumps(
                    {
                        "regression": [{"query": "one", "error": error_value}],
                        "positive": [],
                        "adversarial": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    request = replace(request_for_all_suites(tmp_path), suites=("rag-397",))
    report = run_suites(request, RagCaseErrorRunner())

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
            output.write_text('{"question_id": "one", "hypothesis": "answer"}\n', encoding="utf-8")
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
