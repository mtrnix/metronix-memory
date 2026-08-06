"""Pure orchestration and sanitized reporting for existing memory evaluations.

This module deliberately does not provide a command-line interface.  It runs
the repository's existing evaluators as child processes and links their native
artifacts from a small, versioned report.
"""

from __future__ import annotations

import hashlib
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
from urllib.parse import urlsplit, urlunsplit

SuiteName = Literal["search", "rag-397", "longmemeval"]
SuiteStatus = Literal["passed", "failed", "skipped"]
SummaryValue = float | int | str | bool | None

_RAG_EMAIL_ENV = "METRONIX_ADMIN_EMAIL"
_RAG_PASSWORD_ENV = "METRONIX_ADMIN_PASSWORD"
_ACCURACY_RE = re.compile(
    r"^\s*Accuracy:\s*"
    r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SECRET_ENV_MARKERS = ("API_KEY", "APIKEY", "CREDENTIAL", "PASS", "SECRET", "TOKEN")
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LONGMEMEVAL_ROOT = _REPO_ROOT / "benchmarks" / "longmemeval"
_LONGMEMEVAL_ENV = _LONGMEMEVAL_ROOT / ".env.benchmark"
_LONGMEMEVAL_LEGACY_ENV = _LONGMEMEVAL_ROOT / ".env"
_LONGMEMEVAL_DATASETS = {
    "oracle": {
        "filename": "longmemeval_oracle.json",
        "source": (
            "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
            "resolve/main/longmemeval_oracle.json"
        ),
    },
    "s": {
        "filename": "longmemeval_s_cleaned.json",
        "source": (
            "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
            "resolve/main/longmemeval_s_cleaned.json"
        ),
    },
}

HIGHER_IS_BETTER = frozenset(
    {
        "search.precision_at_k",
        "search.mrr",
        "search.ndcg_at_k",
        "search.negative_accuracy",
        "longmemeval.accuracy",
    }
)

_COMPARISON_CONFIGURATION_KEYS: dict[SuiteName, tuple[str, ...]] = {
    "search": ("workspace", "k", "testset", "include_unstable"),
    "rag-397": ("base_url", "workspace", "credential_environment_variables"),
    "longmemeval": (
        "variant",
        "max_questions",
        "run_judge",
        "metronix_mcp_endpoint",
        "workspace",
        "top_k",
        "chat_model",
        "chat_base_url",
        "judge_model",
        "judge_base_url",
        "dataset",
    ),
}


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
    incompatible_suites: dict[SuiteName, str] = field(default_factory=dict)

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
    deltas = _raw_baseline_deltas(current, baseline)
    return [
        Regression(metric=metric, delta=round(deltas[metric], 12), threshold=limit)
        for metric, limit in thresholds.items()
        if metric in deltas and deltas[metric] < -limit
    ]


def baseline_deltas(current: HarnessReport, baseline: HarnessReport) -> dict[str, float]:
    """Return informational deltas for numeric summary metrics shared by both reports."""
    return {
        metric: round(delta, 12)
        for metric, delta in _raw_baseline_deltas(current, baseline).items()
    }


def _raw_baseline_deltas(current: HarnessReport, baseline: HarnessReport) -> dict[str, float]:
    compatible_suites = set(current.suites) - set(_comparison_incompatibilities(current, baseline))
    current_metrics = _summary_metrics(current, compatible_suites)
    baseline_metrics = _summary_metrics(baseline, compatible_suites)
    return {
        metric: current_metrics[metric] - baseline_metrics[metric]
        for metric in sorted(current_metrics.keys() & baseline_metrics.keys())
    }


def attach_baseline_comparison(
    current: HarnessReport,
    baseline: HarnessReport,
    thresholds: Mapping[str, float],
) -> HarnessReport:
    """Return a report enriched with baseline deltas and threshold breaches."""
    incompatibilities = _comparison_incompatibilities(current, baseline)
    current_metrics = _summary_metrics(current)
    baseline_metrics = _summary_metrics(baseline)
    missing_gate_metrics: dict[str, list[str]] = {}
    for metric in thresholds:
        suite, _, _ = metric.partition(".")
        if suite not in incompatibilities and (
            metric not in current_metrics or metric not in baseline_metrics
        ):
            missing_gate_metrics.setdefault(suite, []).append(metric)
    for suite, metrics in missing_gate_metrics.items():
        incompatibilities[suite] = (
            "configured threshold metrics must be finite numbers in current and "
            f"baseline reports: {', '.join(sorted(metrics))}"
        )
    return replace(
        current,
        deltas=baseline_deltas(current, baseline),
        regressions=compare_baseline(current, baseline, thresholds),
        incompatible_suites=incompatibilities,
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
        "--force",
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
    artifact_path = (request.artifact_dir / _artifact_name(name)).resolve()
    if name == "longmemeval":
        try:
            artifact_path.unlink(missing_ok=True)
        except OSError:
            return _failed_result(
                started_at,
                started,
                {},
                artifact_path,
                None,
                {},
                "Could not remove existing LongMemEval artifact",
                include_artifact=False,
            )
    try:
        command, child_env, configuration, artifact_path, secrets = _suite_invocation(
            name, request
        )
    except Exception:  # noqa: BLE001 - preparation errors must remain suite-local.
        return _failed_result(
            started_at,
            started,
            {},
            artifact_path,
            None,
            {},
            "Could not prepare suite configuration",
            include_artifact=False,
        )

    try:
        completed = runner.run(command, child_env=child_env)
    except Exception:  # noqa: BLE001 - runner errors must be reported per suite.
        return _failed_result(
            started_at,
            started,
            configuration,
            artifact_path,
            None,
            {},
            "Could not start suite process",
        )

    errors: list[str] = []
    if completed.returncode != 0:
        errors.append(_command_failure_message(completed.returncode))

    try:
        summary = _parse_summary(name, artifact_path, completed.stdout, completed.stderr)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        summary = {}
        errors.append(
            _redact_text(f"Could not read expected artifact {artifact_path}: {exc}", secrets)
        )

    errors.extend(_summary_failure_messages(name, summary, configuration))

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


def _summary_metrics(report: HarnessReport, suites: set[str] | None = None) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for suite, result in report.suites.items():
        if suites is not None and suite not in suites:
            continue
        for metric, value in result.summary.items():
            if isinstance(value, bool) or not isinstance(value, (float, int)):
                continue
            numeric_value = float(value)
            if math.isfinite(numeric_value):
                metrics[f"{suite}.{metric}"] = numeric_value
    return metrics


def _comparison_incompatibilities(
    current: HarnessReport, baseline: HarnessReport
) -> dict[SuiteName, str]:
    incompatibilities: dict[SuiteName, str] = {}
    for suite in current.suites:
        if suite not in baseline.suites:
            incompatibilities[suite] = "suite must be present in current and baseline reports"
            continue
        current_result = current.suites[suite]
        baseline_result = baseline.suites[suite]
        if current_result.status != "passed" or baseline_result.status != "passed":
            incompatibilities[suite] = "current and baseline suite status must both be passed"
            continue
        current_configuration = _normalized_suite_configuration(
            suite, current_result.configuration
        )
        baseline_configuration = _normalized_suite_configuration(
            suite, baseline_result.configuration
        )
        if (
            current_configuration is None
            or baseline_configuration is None
            or current_configuration != baseline_configuration
        ):
            incompatibilities[suite] = "current and baseline suite configuration must be identical"
    return incompatibilities


def _normalized_suite_configuration(
    suite: SuiteName, configuration: Mapping[str, object]
) -> str | None:
    keys = _COMPARISON_CONFIGURATION_KEYS.get(suite)
    if keys is None or any(key not in configuration for key in keys):
        return None
    relevant = {key: configuration[key] for key in keys}
    try:
        return json.dumps(relevant, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


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
    effective_configuration = _longmemeval_effective_configuration(config)
    return (
        build_longmemeval_command(config, artifact_path),
        child_env,
        {
            "variant": config.variant,
            "max_questions": config.max_questions,
            "run_judge": config.run_judge,
            **effective_configuration,
        },
        artifact_path,
        _redaction_values(child_env),
    )


def _artifact_name(name: SuiteName) -> str:
    if name == "longmemeval":
        return "longmemeval.jsonl"
    return f"{name}.json"


def _longmemeval_effective_configuration(
    config: LongMemEvalConfig,
) -> dict[str, object]:
    environment = dict(os.environ)
    for key, value in _parse_env_file(_REPO_ROOT / ".env").items():
        environment.setdefault(key, value)

    benchmark_env = _LONGMEMEVAL_ENV
    if not benchmark_env.exists() and _LONGMEMEVAL_LEGACY_ENV.exists():
        benchmark_env = _LONGMEMEVAL_LEGACY_ENV
    for key, value in _parse_env_file(benchmark_env).items():
        if value:
            environment[key] = value
        else:
            environment.setdefault(key, value)

    dataset = _LONGMEMEVAL_DATASETS[config.variant]
    dataset_path = _LONGMEMEVAL_ROOT / "data" / dataset["filename"]
    return {
        "metronix_mcp_endpoint": _sanitized_endpoint_identity(
            environment.get("METRONIX_MCP_URL", "http://localhost:8000/mcp")
        ),
        "workspace": environment.get("LME_WORKSPACE_ID", "MABENCH"),
        "top_k": int(environment.get("LME_RETRIEVE_TOP_K", "10")),
        "chat_model": environment.get("LME_CHAT_MODEL", "gpt-4o-mini"),
        "chat_base_url": environment.get("LME_CHAT_BASE_URL", "https://api.openai.com/v1"),
        "judge_model": environment.get("LME_JUDGE_MODEL", "gpt-4o"),
        "judge_base_url": environment.get("LME_JUDGE_BASE_URL", "https://api.openai.com/v1"),
        "dataset": {
            **dataset,
            "sha256": _sha256_if_present(dataset_path),
        },
    }


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _sanitized_endpoint_identity(value: str) -> str:
    """Return a normalized endpoint identity without URL credentials or parameters."""
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if not scheme or hostname is None:
        raise ValueError("METRONIX_MCP_URL must be an absolute URL")

    hostname = hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _sha256_if_present(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            if isinstance(row, dict) and "error" in row
        ),
    }


def _parse_longmemeval_summary(path: Path, stdout: str, stderr: str) -> dict[str, SummaryValue]:
    answer_count = 0
    error_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("LongMemEval artifact contains a non-object JSON line")
        answer_count += 1
        hypothesis = row.get("hypothesis")
        if isinstance(hypothesis, str) and hypothesis.startswith("Error:"):
            error_count += 1
    match = _ACCURACY_RE.search(f"{stdout}\n{stderr}")
    accuracy = float(match.group(1)) if match else None
    if accuracy is not None and not math.isfinite(accuracy):
        accuracy = None
    return {
        "answer_count": answer_count,
        "error_count": error_count,
        "accuracy": accuracy,
    }


def _summary_failure_messages(
    name: SuiteName,
    summary: Mapping[str, SummaryValue],
    configuration: Mapping[str, object],
) -> list[str]:
    if name == "rag-397" and summary.get("error_count", 0) != 0:
        return ["RAG-397 artifact contains one or more case errors"]
    if name == "longmemeval":
        if summary.get("error_count", 0) != 0:
            return ["LongMemEval artifact contains one or more error hypotheses"]
        accuracy = summary.get("accuracy")
        if configuration.get("run_judge") is True and (
            isinstance(accuracy, bool)
            or not isinstance(accuracy, (float, int))
            or not math.isfinite(float(accuracy))
        ):
            return ["LongMemEval judge did not produce a finite accuracy"]
    return []


def _load_json_object(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("artifact root must be a JSON object")
    return data


def _command_failure_message(exit_code: int) -> str:
    return f"Suite command exited with code {exit_code}"


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
    *,
    include_artifact: bool = True,
) -> SuiteResult:
    return SuiteResult(
        status="failed",
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=round(time.monotonic() - started, 6),
        exit_code=exit_code,
        configuration=configuration,
        artifacts={"native_result": str(artifact_path)} if include_artifact else {},
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
