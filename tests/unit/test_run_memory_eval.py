from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_memory_eval as cli
from scripts.memory_eval_harness import HarnessReport, SuiteResult


def report_with_search(*, status: str = "passed", mrr: float = 0.8) -> HarnessReport:
    return HarnessReport(
        schema_version=1,
        started_at="2026-07-20T00:00:00+00:00",
        finished_at="2026-07-20T00:00:01+00:00",
        requested_suites=["search"],
        suites={
            "search": SuiteResult(
                status=status,  # type: ignore[arg-type]
                started_at="2026-07-20T00:00:00+00:00",
                finished_at="2026-07-20T00:00:01+00:00",
                duration_seconds=1.0,
                exit_code=0 if status == "passed" else 1,
                configuration={},
                artifacts={},
                summary={"mrr": mrr},
                error="failed" if status == "failed" else None,
            )
        },
    )


def test_cli_rejects_unknown_suite_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "run_suites", lambda *_: pytest.fail("must not run suites"))

    assert cli.main(["--suites", "search,unknown"]) == 2


def test_cli_validates_threshold_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run_suites", lambda *_: pytest.fail("must not run suites"))

    assert cli.main(["--suites", "search", "--max-regression", "rag-397.error_count=1"]) == 2


def test_cli_rejects_unwritable_output_parent_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_parent = tmp_path / "not-a-directory"
    output_parent.write_text("file", encoding="utf-8")
    monkeypatch.setattr(cli, "run_suites", lambda *_: pytest.fail("must not run suites"))

    assert cli.main(["--suites", "search", "--output", str(output_parent / "report.json")]) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 999),
        ("schema_version", True),
        ("schema_version", 1.0),
        ("requested_suites", ["unexpected"]),
    ],
)
def test_cli_rejects_incompatible_baseline_before_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    baseline_data = report_with_search().to_dict()
    baseline_data[field] = value
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(baseline_data), encoding="utf-8")
    monkeypatch.setattr(cli, "run_suites", lambda *_: pytest.fail("must not run suites"))

    assert cli.main(["--suites", "search", "--baseline", str(baseline)]) == 2


def test_cli_rejects_non_scalar_baseline_summary_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_data = report_with_search().to_dict()
    baseline_data["suites"]["search"]["summary"] = {"mrr": []}
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(baseline_data), encoding="utf-8")
    monkeypatch.setattr(cli, "run_suites", lambda *_: pytest.fail("must not run suites"))

    assert cli.main(["--suites", "search", "--baseline", str(baseline)]) == 2


def test_cli_returns_one_for_suite_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "run_suites", lambda *_: report_with_search(status="failed"))

    output = tmp_path / "report.json"
    assert cli.main(["--suites", "search", "--output", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["suites"]["search"]["status"] == "failed"


def test_cli_returns_one_for_regression_breach(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(report_with_search(mrr=0.9).to_dict()), encoding="utf-8")
    monkeypatch.setattr(cli, "run_suites", lambda *_: report_with_search(mrr=0.8))

    output = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "--suites",
                "search",
                "--baseline",
                str(baseline),
                "--max-regression",
                "search.mrr=0.05",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert json.loads(output.read_text(encoding="utf-8"))["regressions"] == [
        {"delta": -0.1, "metric": "search.mrr", "threshold": 0.05}
    ]


def test_cli_uses_selected_suite_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requests = []
    monkeypatch.setattr(
        cli,
        "run_suites",
        lambda request, _: requests.append(request) or report_with_search(),
    )

    assert (
        cli.main(
            [
                "--suites",
                "search",
                "--search-workspace",
                "CUSTOM",
                "--search-k",
                "7",
                "--search-testset",
                "fixtures/eval.json",
                "--include-unstable",
                "--output",
                str(tmp_path / "report.json"),
            ]
        )
        == 0
    )

    request = requests[0]
    assert request.suites == ("search",)
    assert request.search is not None
    assert request.search.workspace == "CUSTOM"
    assert request.search.k == 7
    assert request.search.testset == Path("fixtures/eval.json")
    assert request.search.include_unstable is True
    assert request.rag_397 is None
    assert request.longmemeval is None
