from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks._shared import manifest


def test_question_ids_digest_is_order_sensitive() -> None:
    a = manifest.question_ids_digest(["q1", "q2", "q3"])
    b = manifest.question_ids_digest(["q1", "q3", "q2"])
    c = manifest.question_ids_digest(["q1", "q2"])
    assert a != b != c
    assert a == manifest.question_ids_digest(["q1", "q2", "q3"])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:8000/mcp/", "http://localhost:8000/mcp"),
        ("https://user:pass@Metronix.Example:443/mcp/?t=secret#x", "https://metronix.example/mcp"),
        ("http://host:80/", "http://host"),
        ("https://[::1]:8443/mcp", "https://[::1]:8443/mcp"),
    ],
)
def test_sanitized_endpoint_identity_drops_credentials_and_defaults(
    url: str, expected: str
) -> None:
    assert manifest.sanitized_endpoint_identity(url) == expected


def test_sanitized_endpoint_identity_rejects_relative() -> None:
    with pytest.raises(ValueError, match="absolute URL"):
        manifest.sanitized_endpoint_identity("/mcp")


def test_git_revision_reports_repo_state() -> None:
    info = manifest.git_revision(Path(__file__).resolve().parents[4])
    assert info["revision"] != "unknown"
    assert len(info["revision"]) == 40
    assert isinstance(info["dirty"], bool)


def test_git_revision_tolerates_non_repo(tmp_path: Path) -> None:
    info = manifest.git_revision(tmp_path)
    assert info == {"revision": "unknown", "dirty": None}


def test_build_query_set_and_summary_round_trip() -> None:
    qs = manifest.build_query_set(
        benchmark="locomo",
        selector={"categories": [1, 2]},
        question_ids=["a", "b", "c"],
    )
    assert qs["question_count"] == 3
    assert qs["question_ids_sha256"] == manifest.question_ids_digest(["a", "b", "c"])
    summary = manifest.query_set_summary(qs)
    assert "question_ids" not in summary
    assert summary["question_ids_sha256"] == qs["question_ids_sha256"]
    assert summary["selector"] == {"categories": [1, 2]}


def test_build_manifest_embeds_query_set_summary_not_ids(tmp_path: Path) -> None:
    qs = manifest.build_query_set(
        benchmark="longmemeval", selector={"variant": "s"}, question_ids=["q1", "q2"]
    )
    m = manifest.build_manifest(
        benchmark="longmemeval",
        repo_root=tmp_path,
        dataset={"name": "x", "sha256": "deadbeef"},
        query_set=qs,
        config={"top_k": 10},
        stack={"mcp_endpoint_identity": "http://localhost:8000/mcp"},
        metrics_requested=["recall_at_10"],
        run_id="fixed",
    )
    assert m["schema_version"] == manifest.MANIFEST_SCHEMA_VERSION
    assert m["run_id"] == "fixed"
    assert m["query_set"] == manifest.query_set_summary(qs)
    assert "question_ids" not in m["query_set"]
    assert m["repository"] == {"revision": "unknown", "dirty": None}


def test_write_run_artifacts_writes_both_sidecars(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "answers.jsonl"
    qs = manifest.build_query_set(benchmark="locomo", selector={}, question_ids=["a"])
    m = manifest.build_manifest(
        benchmark="locomo",
        repo_root=tmp_path,
        dataset={},
        query_set=qs,
        config={},
        stack={},
        metrics_requested=[],
    )
    m_path, q_path = manifest.write_run_artifacts(out, manifest=m, query_set=qs)

    assert m_path == out.with_suffix(".jsonl.manifest.json")
    assert q_path == out.with_suffix(".jsonl.query_set.json")
    reloaded = manifest.load_query_set(q_path)
    assert reloaded["question_ids"] == ["a"]
    # sorted keys + trailing newline
    text = m_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)["benchmark"] == "locomo"


def test_load_query_set_rejects_non_query_set(tmp_path: Path) -> None:
    bad = tmp_path / "x.json"
    bad.write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="query_set"):
        manifest.load_query_set(bad)
