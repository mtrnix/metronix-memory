"""Pure orchestration and sanitized reporting for existing memory evaluations.

This module deliberately does not provide a command-line interface.  It runs
the repository's existing evaluators as child processes and links their native
artifacts from a small, versioned report.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

SuiteName = Literal["search", "rag-397", "longmemeval"]
SuiteStatus = Literal["passed", "failed", "skipped"]
SummaryValue = float | int | str | bool | None

_RAG_EMAIL_ENV = "METRONIX_ADMIN_EMAIL"
_RAG_PASSWORD_ENV = "METRONIX_ADMIN_PASSWORD"
_ACCURACY_RE = re.compile(r"Accuracy:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_SECRET_ENV_MARKERS = ("API_KEY", "APIKEY", "CREDENTIAL", "PASS", "SECRET", "TOKEN")

HIGHER_IS_BETTER = frozenset(
    {
        "search.precision_at_k",
        "search.mrr",
        "search.ndcg_at_k",
        "search.negative_accuracy",
        "longmemeval.accuracy",
    }
)


@dataclass(frozen=True)
class SearchConfig:
    workspace: str
    k: int
    testset: Path | None
    include_unstable: bool


@dataclass(frozen=True)
class Rag397Config:
    base_url: str
    workspace: str
    admin_email: str
    admin_password: str


@dataclass(frozen=True)
class LongMemEvalConfig:
    variant: str
    max_questions: int | None
    run_judge: bool


@dataclass(frozen=True)
class HarnessRequest:
    suites: tuple[SuiteName, ...]
    artifact_dir: Path
    search: SearchConfig | None
    rag_397: Rag397Config | None
    longmemeval: LongMemEvalConfig | None


@dataclass(frozen=True)
class SuiteResult:
    status: SuiteStatus
    started_at: str
    finished_at: str
    duration_seconds: float
    exit_code: int | None
    configuration: dict[str, object]
    artifacts: dict[str, str]
    summary: dict[str, SummaryValue]
    error: str | None = None


@dataclass(frozen=True)
class Regression:
    metric: str
    delta: float
    threshold: float


@dataclass(frozen=True)
class HarnessReport:
    schema_version: int
    started_at: str
    finished_at: str
    requested_suites: list[SuiteName]
    suites: dict[SuiteName, SuiteResult]
    regressions: list[Regression] = field(default_factory=list)
    deltas: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation that omits all secret values."""
        return asdict(self)


class CommandRunner:
    """Run one evaluator command while capturing its native terminal output."""

    def run(
        self,
        command: Sequence[str],
        *,
        child_env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=dict(child_env),
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_threshold(value: str) -> tuple[str, float]:
    """Parse one ``suite.metric=maximum-decline`` CLI value."""
    key, separator, raw_limit = value.partition("=")
    try:
        limit = float(raw_limit)
    except ValueError as exc:
        raise ValueError("threshold must be suite.metric=non-negative-number") from exc
    if not separator or not key or not math.isfinite(limit) or limit < 0:
        raise ValueError("threshold must be suite.metric=non-negative-number")
    if key not in HIGHER_IS_BETTER:
        raise ValueError(f"unknown threshold metric: {key}")
    return key, limit


def compare_baseline(
    current: HarnessReport,
    baseline: HarnessReport,
    thresholds: Mapping[str, float],
) -> list[Regression]:
    """Return quality-gate breaches for comparable, higher-is-better metrics."""
    _validate_thresholds(thresholds)
    deltas = baseline_deltas(current, baseline)
    return [
        Regression(metric=metric, delta=deltas[metric], threshold=limit)
        for metric, limit in thresholds.items()
        if metric in deltas and deltas[metric] < -limit
    ]


def baseline_deltas(current: HarnessReport, baseline: HarnessReport) -> dict[str, float]:
    """Return informational deltas for numeric summary metrics shared by both reports."""
    current_metrics = _summary_metrics(current)
    baseline_metrics = _summary_metrics(baseline)
    return {
        metric: round(current_metrics[metric] - baseline_metrics[metric], 12)
        for metric in sorted(current_metrics.keys() & baseline_metrics.keys())
    }


def attach_baseline_comparison(
    current: HarnessReport,
    baseline: HarnessReport,
    thresholds: Mapping[str, float],
) -> HarnessReport:
    """Return a report enriched with baseline deltas and threshold breaches."""
    return replace(
        current,
        deltas=baseline_deltas(current, baseline),
        regressions=compare_baseline(current, baseline, thresholds),
    )


def build_search_command(config: SearchConfig, output: Path) -> list[str]:
    command = [
        sys.executable,
        "scripts/run_eval.py",
        "--workspace",
        config.workspace,
        "--k",
        str(config.k),
    ]
    if config.testset is not None:
        command.extend(("--testset", str(config.testset)))
    if config.include_unstable:
        command.append("--all")
    command.extend(("--output", str(output)))
    return command


def build_rag_397_command() -> list[str]:
    """Build a static command that expands RAG credentials only in the child."""
    return [
        "bash",
        "-c",
        (
            'exec "$0" scripts/rag_eval_397.py '
            '--base-url "$METRONIX_EVAL_RAG_BASE_URL" '
            f'--email "${_RAG_EMAIL_ENV}" '
            f'--password "${_RAG_PASSWORD_ENV}" '
            '--workspace "$METRONIX_EVAL_RAG_WORKSPACE" '
            '--out "$METRONIX_EVAL_RAG_ARTIFACT"'
        ),
        sys.executable,
    ]


def build_longmemeval_command(config: LongMemEvalConfig, output: Path) -> list[str]:
    command = [
        "bash",
        "benchmarks/longmemeval/run.sh",
        "--variant",
        config.variant,
        "--output",
        str(output),
    ]
    if config.max_questions is not None:
        command.extend(("--max-questions", str(config.max_questions)))
    if not config.run_judge:
        command.append("--run-only")
    return command


def run_suites(request: HarnessRequest, runner: CommandRunner) -> HarnessReport:
    """Run every requested suite, preserving results after a prior failure."""
    started_at = utc_now()
    request.artifact_dir.mkdir(parents=True, exist_ok=True)
    results = {name: run_one_suite(name, request, runner) for name in request.suites}
    return HarnessReport(
        schema_version=1,
        started_at=started_at,
        finished_at=utc_now(),
        requested_suites=list(request.suites),
        suites=results,
        regressions=[],
    )


def run_one_suite(name: SuiteName, request: HarnessRequest, runner: CommandRunner) -> SuiteResult:
    started_at = utc_now()
    started = time.monotonic()
    try:
        command, child_env, configuration, artifact_path, secrets = _suite_invocation(
            name, request
        )
    except ValueError as exc:
        return _skipped_result(started_at, started, str(exc))

    try:
        completed = runner.run(command, child_env=child_env)
    except Exception as exc:  # noqa: BLE001 - runner errors must be reported per suite.
        return _failed_result(
            started_at,
            started,
            configuration,
            artifact_path,
            None,
            {},
            _redact_text(f"Could not start suite: {exc}", secrets),
        )

    errors: list[str] = []
    if completed.returncode != 0:
        errors.append(
            _redact_text(
                _command_failure_message(completed.returncode, completed.stdout, completed.stderr),
                secrets,
            )
        )

    try:
        summary = _parse_summary(name, artifact_path, completed.stdout, completed.stderr)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        summary = {}
        errors.append(
            _redact_text(f"Could not read expected artifact {artifact_path}: {exc}", secrets)
        )

    if errors:
        return _failed_result(
            started_at,
            started,
            configuration,
            artifact_path,
            completed.returncode,
            summary,
            " ".join(errors),
        )

    return SuiteResult(
        status="passed",
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=round(time.monotonic() - started, 6),
        exit_code=completed.returncode,
        configuration=configuration,
        artifacts={"native_result": str(artifact_path)},
        summary=summary,
    )


def write_report(report: HarnessReport, path: Path) -> None:
    """Write a report without embedding raw evaluator output or credentials."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def _validate_thresholds(thresholds: Mapping[str, float]) -> None:
    for metric, limit in thresholds.items():
        if metric not in HIGHER_IS_BETTER:
            raise ValueError(f"unknown threshold metric: {metric}")
        if isinstance(limit, bool) or not isinstance(limit, (float, int)):
            raise ValueError(f"threshold for {metric} must be a non-negative number")
        if not math.isfinite(float(limit)) or limit < 0:
            raise ValueError(f"threshold for {metric} must be a non-negative number")


def _summary_metrics(report: HarnessReport) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for suite, result in report.suites.items():
        for metric, value in result.summary.items():
            if isinstance(value, bool) or not isinstance(value, (float, int)):
                continue
            numeric_value = float(value)
            if math.isfinite(numeric_value):
                metrics[f"{suite}.{metric}"] = numeric_value
    return metrics


def _suite_invocation(
    name: SuiteName, request: HarnessRequest
) -> tuple[list[str], dict[str, str], dict[str, object], Path, tuple[str, ...]]:
    artifact_path = (request.artifact_dir / _artifact_name(name)).resolve()
    child_env = dict(os.environ)
    child_env["METRONIX_EVAL_SUITE"] = name
    child_env["METRONIX_EVAL_ARTIFACT"] = str(artifact_path)

    if name == "search":
        if request.search is None:
            raise ValueError("Search configuration was not provided")
        config = request.search
        return (
            build_search_command(config, artifact_path),
            child_env,
            {
                "workspace": config.workspace,
                "k": config.k,
                "testset": str(config.testset) if config.testset is not None else None,
                "include_unstable": config.include_unstable,
            },
            artifact_path,
            _redaction_values(child_env),
        )

    if name == "rag-397":
        if request.rag_397 is None:
            raise ValueError("RAG-397 configuration was not provided")
        config = request.rag_397
        child_env.update(
            {
                "METRONIX_EVAL_RAG_BASE_URL": config.base_url,
                "METRONIX_EVAL_RAG_WORKSPACE": config.workspace,
                "METRONIX_EVAL_RAG_ARTIFACT": str(artifact_path),
                _RAG_EMAIL_ENV: config.admin_email,
                _RAG_PASSWORD_ENV: config.admin_password,
            }
        )
        return (
            build_rag_397_command(),
            child_env,
            {
                "base_url": config.base_url,
                "workspace": config.workspace,
                "credential_environment_variables": [_RAG_EMAIL_ENV, _RAG_PASSWORD_ENV],
            },
            artifact_path,
            _redaction_values(child_env, config.admin_email),
        )

    if request.longmemeval is None:
        raise ValueError("LongMemEval configuration was not provided")
    config = request.longmemeval
    return (
        build_longmemeval_command(config, artifact_path),
        child_env,
        {
            "variant": config.variant,
            "max_questions": config.max_questions,
            "run_judge": config.run_judge,
        },
        artifact_path,
        _redaction_values(child_env),
    )


def _artifact_name(name: SuiteName) -> str:
    if name == "longmemeval":
        return "longmemeval.jsonl"
    return f"{name}.json"


def _parse_summary(
    name: SuiteName,
    artifact_path: Path,
    stdout: str,
    stderr: str,
) -> dict[str, SummaryValue]:
    if name == "search":
        return _parse_search_summary(artifact_path)
    if name == "rag-397":
        return _parse_rag_397_summary(artifact_path)
    return _parse_longmemeval_summary(artifact_path, stdout, stderr)


def _parse_search_summary(path: Path) -> dict[str, SummaryValue]:
    data = _load_json_object(path)
    averages = data.get("averages")
    if not isinstance(averages, dict):
        raise ValueError("search artifact has no averages object")
    summary: dict[str, SummaryValue] = {}
    for key, value in averages.items():
        if not isinstance(key, str) or not isinstance(value, (float, int, str, bool, type(None))):
            raise ValueError("search averages contain a non-scalar value")
        summary[key] = value
    return summary


def _parse_rag_397_summary(path: Path) -> dict[str, SummaryValue]:
    data = _load_json_object(path)
    buckets = ("regression", "positive", "adversarial")
    rows: dict[str, list[object]] = {}
    for bucket in buckets:
        value = data.get(bucket)
        if not isinstance(value, list):
            raise ValueError(f"RAG-397 artifact has no {bucket} list")
        rows[bucket] = value
    return {
        **{f"{bucket}_count": len(rows[bucket]) for bucket in buckets},
        "error_count": sum(
            1
            for bucket_rows in rows.values()
            for row in bucket_rows
            if isinstance(row, dict) and row.get("error")
        ),
    }


def _parse_longmemeval_summary(path: Path, stdout: str, stderr: str) -> dict[str, SummaryValue]:
    answer_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if not isinstance(json.loads(line), dict):
            raise ValueError("LongMemEval artifact contains a non-object JSON line")
        answer_count += 1
    match = _ACCURACY_RE.search(f"{stdout}\n{stderr}")
    return {
        "answer_count": answer_count,
        "accuracy": float(match.group(1)) if match else None,
    }


def _load_json_object(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("artifact root must be a JSON object")
    return data


def _command_failure_message(exit_code: int, stdout: str, stderr: str) -> str:
    output = (stderr or stdout).strip()
    if not output:
        return f"Suite command exited with code {exit_code}"
    return f"Suite command exited with code {exit_code}: {output[:1000]}"


def _redact_text(text: str, secrets: Sequence[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _redaction_values(child_env: Mapping[str, str], *additional_values: str) -> tuple[str, ...]:
    values = [
        value
        for name, value in child_env.items()
        if value and any(marker in name.upper() for marker in _SECRET_ENV_MARKERS)
    ]
    values.extend(value for value in additional_values if value)
    return tuple(dict.fromkeys(values))


def _failed_result(
    started_at: str,
    started: float,
    configuration: dict[str, object],
    artifact_path: Path,
    exit_code: int | None,
    summary: dict[str, SummaryValue],
    error: str,
) -> SuiteResult:
    return SuiteResult(
        status="failed",
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=round(time.monotonic() - started, 6),
        exit_code=exit_code,
        configuration=configuration,
        artifacts={"native_result": str(artifact_path)},
        summary=summary,
        error=error,
    )


def _skipped_result(started_at: str, started: float, error: str) -> SuiteResult:
    return SuiteResult(
        status="skipped",
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=round(time.monotonic() - started, 6),
        exit_code=None,
        configuration={},
        artifacts={},
        summary={},
        error=error,
    )
