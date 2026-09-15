from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks._shared import compare


def _write_lme_run(
    directory: Path,
    *,
    name: str = "answers.jsonl",
    mode: str = "flag-off",
    dataset_sha: str = "d" * 64,
    qids_sha: str = "q" * 64,
    revision: str = "a" * 40,
    dirty: bool = False,
    recall10: float = 0.72,
    recall5: float = 0.61,
    eligible: int = 90,
    suspect_count: int = 0,
    search_p95: float = 380.0,
    top_k: int = 10,
    chat_model: str = "gpt-4o-mini",
    chat_temperature: float = 0.0,
    workspace: str = "MABENCH",
    endpoint: str = "http://localhost:8000/mcp",
    workspace_reset: str = "no",
    probe: dict | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    results = directory / name
    results.write_text('{"question_id": "q1", "hypothesis": "x"}\n', encoding="utf-8")
    (directory / f"{name}.manifest.json").write_text(
        json.dumps(
            {
                "benchmark": "longmemeval",
                "run_id": f"run-{mode}",
                "repository": {"revision": revision, "dirty": dirty},
                "dataset": {"sha256": dataset_sha},
                "config": {
                    "top_k": top_k,
                    "workspace": workspace,
                    "chat_model": chat_model,
                    "chat_temperature": chat_temperature,
                    "judge_model": "gpt-4o",
                },
                "stack": {
                    "mcp_endpoint_identity": endpoint,
                    "operator_declared_retrieval_mode": mode,
                    "workspace_reset": workspace_reset,
                    "probe": probe if probe is not None else {},
                },
            }
        ),
        encoding="utf-8",
    )
    (directory / f"{name}.query_set.json").write_text(
        json.dumps({"question_ids_sha256": qids_sha, "question_ids": ["q1"]}), encoding="utf-8"
    )
    (directory / f"{name}.retrieval.eval.json").write_text(
        json.dumps(
            {
                "eligible_count": eligible,
                "suspect_count": suspect_count,
                "recall": {"5": recall5, "10": recall10},
                "latency": {"phases": {"search_ms": {"p50_ms": 200.0, "p95_ms": search_p95}}},
            }
        ),
        encoding="utf-8",
    )
    return results


def test_load_run_requires_sidecars(tmp_path: Path) -> None:
    (tmp_path / "answers.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="manifest"):
        compare.load_run(tmp_path / "answers.jsonl")


def test_metrics_longmemeval_from_retrieval_eval(tmp_path: Path) -> None:
    run = compare.load_run(_write_lme_run(tmp_path, recall10=0.8, recall5=0.65))
    m = compare.metrics(run)
    assert m["benchmark"] == "longmemeval"
    assert m["recall_at_10"] == 0.8
    assert m["recall_at_5"] == 0.65
    assert m["search_latency_p95_ms"] == 380.0
    assert m["error_count"] == 0


def test_metrics_locomo_from_eval_json(tmp_path: Path) -> None:
    name = "answers.jsonl"
    (tmp_path / name).write_text("{}\n", encoding="utf-8")
    (tmp_path / f"{name}.manifest.json").write_text(
        json.dumps({"benchmark": "locomo", "repository": {"dirty": False}}), encoding="utf-8"
    )
    (tmp_path / f"{name}.query_set.json").write_text(
        json.dumps({"question_ids_sha256": "z" * 64}), encoding="utf-8"
    )
    (tmp_path / f"{name}.eval.json").write_text(
        json.dumps(
            {
                "overall_score": 0.55,
                "error_count": 0,
                "retrieval": {"eligible_count": 1200, "recall": {"5": 0.5, "10": 0.7}},
                "latency": {"phases": {"search_ms": {"p95_ms": 250.0}}},
            }
        ),
        encoding="utf-8",
    )
    m = compare.metrics(compare.load_run(tmp_path / name))
    assert m["recall_at_10"] == 0.7
    assert m["answer_metric"] == 0.55
    assert m["answer_metric_name"] == "token_f1"


def test_comparable_pair_passes(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off", recall10=0.70))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", recall10=0.74))
    report = compare.compare(base, cur)
    assert report["comparable"] is True
    assert report["verdict"] == "PASS"
    assert report["metrics"]["recall_at_10"] == {
        "baseline": 0.70,
        "current": 0.74,
        "delta": pytest.approx(0.04),
    }


@pytest.mark.parametrize(
    ("kwarg", "value"),
    [
        ("dataset_sha", "e" * 64),
        ("qids_sha", "w" * 64),
        ("revision", "b" * 40),
        ("top_k", 20),
        ("chat_model", "gpt-4o"),
        ("chat_temperature", 0.7),
        ("workspace", "OTHER"),
        ("endpoint", "https://other/mcp"),
        ("workspace_reset", "reset"),
    ],
)
def test_identity_mismatch_blocks_comparison(tmp_path: Path, kwarg: str, value: object) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off"))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", **{kwarg: value}))
    report = compare.compare(base, cur)
    assert report["comparable"] is False
    assert report["verdict"] == "FAIL"
    assert report["incompatibilities"]


def test_stack_probe_mismatch_blocks_comparison(tmp_path: Path) -> None:
    base = compare.load_run(
        _write_lme_run(tmp_path / "off", mode="flag-off", probe={"qdrant": "connected"})
    )
    cur = compare.load_run(
        _write_lme_run(tmp_path / "on", mode="flag-on", probe={"qdrant": "unavailable"})
    )
    report = compare.compare(base, cur)
    assert report["comparable"] is False
    assert any("stack probe qdrant" in reason for reason in report["incompatibilities"])


def test_matching_stack_probe_is_comparable(tmp_path: Path) -> None:
    probe = {"qdrant": "connected", "neo4j": "connected", "qdrant_collections": 4}
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off", probe=probe))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", probe=probe))
    assert compare.compare(base, cur)["comparable"] is True


def test_suspect_search_rows_block_comparison(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off"))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", suspect_count=3))
    report = compare.compare(base, cur)
    assert report["comparable"] is False
    assert any("degraded retrieval leg" in reason for reason in report["incompatibilities"])


def test_dirty_run_blocks_unless_allowed(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off"))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", dirty=True))
    assert compare.compare(base, cur)["comparable"] is False
    assert compare.compare(base, cur, allow_dirty=True)["comparable"] is True


def test_same_mode_blocks_unless_allowed(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "a", mode="flag-off"))
    cur = compare.load_run(_write_lme_run(tmp_path / "b", mode="flag-off"))
    assert compare.compare(base, cur)["comparable"] is False
    assert compare.compare(base, cur, allow_same_mode=True)["comparable"] is True


def test_gate_floor_fails_when_current_below(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off", recall10=0.7))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", recall10=0.55))
    report = compare.compare(base, cur, gates={"recall_at_10": 0.60})
    assert report["verdict"] == "FAIL"
    assert report["gate_failures"] and "0.5500" in report["gate_failures"][0]


def test_max_regression_fails_on_decline(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off", recall10=0.80))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on", recall10=0.74))
    report = compare.compare(base, cur, max_regressions={"recall_at_10": 0.03})
    assert report["verdict"] == "FAIL"
    assert report["regressions"]


def test_unknown_gate_metric_rejected(tmp_path: Path) -> None:
    base = compare.load_run(_write_lme_run(tmp_path / "off", mode="flag-off"))
    cur = compare.load_run(_write_lme_run(tmp_path / "on", mode="flag-on"))
    with pytest.raises(ValueError, match="unknown gate metric"):
        compare.compare(base, cur, gates={"mrr": 0.5})


def test_parse_metric_assignment() -> None:
    assert compare.parse_metric_assignment("recall_at_10=0.62") == ("recall_at_10", 0.62)
    with pytest.raises(ValueError, match="METRIC=NUMBER"):
        compare.parse_metric_assignment("recall_at_10=high")
