"""Run selected Metronix memory evaluations and write one sanitized report."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from scripts.memory_eval_harness import (
        CommandRunner,
        HarnessReport,
        HarnessRequest,
        LongMemEvalConfig,
        Rag397Config,
        SearchConfig,
        SuiteResult,
        attach_baseline_comparison,
        parse_threshold,
        run_suites,
        write_report,
    )
else:
    from memory_eval_harness import (
        CommandRunner,
        HarnessReport,
        HarnessRequest,
        LongMemEvalConfig,
        Rag397Config,
        SearchConfig,
        SuiteResult,
        attach_baseline_comparison,
        parse_threshold,
        run_suites,
        write_report,
    )


_SUITES = ("search", "rag-397", "longmemeval")
_SCHEMA_VERSION = 1
_RAG_EMAIL_ENV = "METRONIX_ADMIN_EMAIL"
_RAG_PASSWORD_ENV = "METRONIX_ADMIN_PASSWORD"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run selected Metronix memory evaluations and write one sanitized report."
    )
    parser.add_argument(
        "--suites",
        default=",".join(_SUITES),
        help="Comma-separated suite names: search,rag-397,longmemeval (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the unified JSON report here (default: results/memory-eval/<timestamp>.json)",
    )
    parser.add_argument(
        "--baseline", type=Path, help="Previous unified JSON report for comparison"
    )
    parser.add_argument(
        "--max-regression",
        action="append",
        default=[],
        metavar="SUITE.METRIC=VALUE",
        help="Maximum permitted decline; repeat for each quality gate",
    )

    search = parser.add_argument_group("search configuration")
    search.add_argument("--search-workspace", default="MTRNIX")
    search.add_argument("--search-k", type=_positive_int, default=10)
    search.add_argument("--search-testset", type=Path)
    search.add_argument("--include-unstable", action="store_true")

    rag = parser.add_argument_group("RAG-397 configuration")
    rag.add_argument("--rag-397-base-url", default="http://localhost:8000")
    rag.add_argument("--rag-397-workspace", default="MTRNIX")

    longmemeval = parser.add_argument_group("LongMemEval configuration")
    longmemeval.add_argument("--longmemeval-variant", choices=("oracle", "s"), default="s")
    longmemeval.add_argument("--longmemeval-max-questions", type=_positive_int)
    longmemeval.add_argument(
        "--longmemeval-run-only",
        action="store_true",
        help="Skip the external LLM judge after generating hypotheses",
    )
    return parser


def _selected_suites(value: str) -> tuple[str, ...]:
    suites = tuple(item.strip() for item in value.split(","))
    if not suites or any(not suite for suite in suites):
        raise ValueError("--suites must be a non-empty comma-separated list")
    invalid = sorted(set(suites) - set(_SUITES))
    if invalid:
        raise ValueError(f"unknown suite: {', '.join(invalid)}")
    if len(set(suites)) != len(suites):
        raise ValueError("--suites must not contain duplicates")
    return suites


def _thresholds(values: Sequence[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for value in values:
        metric, limit = parse_threshold(value)
        if metric in thresholds:
            raise ValueError(f"duplicate threshold metric: {metric}")
        thresholds[metric] = limit
    return thresholds


def _report_path(path: Path | None) -> Path:
    if path is not None:
        return path
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return Path("results") / "memory-eval" / f"{timestamp}.json"


def _prepare_output(path: Path) -> Path:
    artifact_dir = path.parent / f"{path.stem}.artifacts"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir():
            raise ValueError(f"output path is a directory: {path}")
        artifact_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"could not prepare output path {path}: {exc}") from exc
    return artifact_dir


def _load_baseline(path: Path) -> HarnessReport:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read baseline report {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("baseline report must be a JSON object")

    try:
        requested_suites = data["requested_suites"]
        suites_data = data["suites"]
        if (
            isinstance(data["schema_version"], bool)
            or not isinstance(data["schema_version"], int)
            or data["schema_version"] != _SCHEMA_VERSION
            or not isinstance(data["started_at"], str)
            or not isinstance(data["finished_at"], str)
            or not isinstance(requested_suites, list)
            or not all(isinstance(suite, str) for suite in requested_suites)
            or not isinstance(suites_data, dict)
        ):
            raise TypeError
        suites = {
            name: _suite_result(value)
            for name, value in suites_data.items()
            if isinstance(name, str)
        }
        if (
            len(suites) != len(suites_data)
            or len(set(requested_suites)) != len(requested_suites)
            or not set(requested_suites).issubset(_SUITES)
            or not set(suites).issubset(_SUITES)
            or set(requested_suites) != set(suites)
        ):
            raise TypeError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("baseline report does not match the memory-eval report schema") from exc

    return HarnessReport(
        schema_version=_SCHEMA_VERSION,
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        requested_suites=requested_suites,
        suites=suites,
    )


def _suite_result(value: object) -> SuiteResult:
    if not isinstance(value, dict):
        raise TypeError
    status = value["status"]
    exit_code = value["exit_code"]
    duration = value["duration_seconds"]
    configuration = value["configuration"]
    artifacts = value["artifacts"]
    summary = value["summary"]
    error = value.get("error")
    if (
        status not in {"passed", "failed", "skipped"}
        or not isinstance(value["started_at"], str)
        or not isinstance(value["finished_at"], str)
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or (
            exit_code is not None
            and (isinstance(exit_code, bool) or not isinstance(exit_code, int))
        )
        or not isinstance(configuration, dict)
        or not all(isinstance(key, str) for key in configuration)
        or not isinstance(artifacts, dict)
        or not all(
            isinstance(key, str) and isinstance(path, str) for key, path in artifacts.items()
        )
        or not _summary_is_valid(summary)
        or (error is not None and not isinstance(error, str))
    ):
        raise TypeError
    return SuiteResult(
        status=status,
        started_at=value["started_at"],
        finished_at=value["finished_at"],
        duration_seconds=float(duration),
        exit_code=exit_code,
        configuration=configuration,
        artifacts=artifacts,
        summary=summary,
        error=error,
    )


def _summary_is_valid(summary: object) -> bool:
    if not isinstance(summary, dict) or not all(isinstance(key, str) for key in summary):
        return False
    for value in summary.values():
        if isinstance(value, bool) or value is None or isinstance(value, str):
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return False
    return True


def _request(
    args: argparse.Namespace, suites: tuple[str, ...], artifact_dir: Path
) -> HarnessRequest:
    rag_config = None
    if "rag-397" in suites:
        admin_email = os.environ.get(_RAG_EMAIL_ENV)
        admin_password = os.environ.get(_RAG_PASSWORD_ENV)
        if not admin_email or not admin_password:
            raise ValueError(
                f"rag-397 requires {_RAG_EMAIL_ENV} and {_RAG_PASSWORD_ENV} environment variables"
            )
        rag_config = Rag397Config(
            base_url=args.rag_397_base_url,
            workspace=args.rag_397_workspace,
            admin_email=admin_email,
            admin_password=admin_password,
        )

    return HarnessRequest(
        suites=suites,  # type: ignore[arg-type]
        artifact_dir=artifact_dir,
        search=(
            SearchConfig(
                workspace=args.search_workspace,
                k=args.search_k,
                testset=args.search_testset,
                include_unstable=args.include_unstable,
            )
            if "search" in suites
            else None
        ),
        rag_397=rag_config,
        longmemeval=(
            LongMemEvalConfig(
                variant=args.longmemeval_variant,
                max_questions=args.longmemeval_max_questions,
                run_judge=not args.longmemeval_run_only,
            )
            if "longmemeval" in suites
            else None
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        suites = _selected_suites(args.suites)
        thresholds = _thresholds(args.max_regression)
        output = _report_path(args.output)
        baseline = _load_baseline(args.baseline) if args.baseline is not None else None
        artifact_dir = _prepare_output(output)
        request = _request(args, suites, artifact_dir)
    except ValueError as exc:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 2

    report = run_suites(request, CommandRunner())
    if baseline is not None:
        report = attach_baseline_comparison(report, baseline, thresholds)
    write_report(report, output)

    suite_failed = any(result.status == "failed" for result in report.suites.values())
    return 1 if suite_failed or report.regressions else 0


if __name__ == "__main__":
    sys.exit(main())
