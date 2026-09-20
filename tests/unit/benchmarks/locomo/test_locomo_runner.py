from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from benchmarks._shared import manifest as run_manifest
from benchmarks.locomo.scripts import run_benchmark
from benchmarks.locomo.scripts.env_config import BenchConfig
from benchmarks.locomo.scripts.run_benchmark import (
    build_run_artifacts,
    chat_complete,
    parse_categories,
    write_manifest,
)


def config() -> BenchConfig:
    return BenchConfig(
        metronix_mcp_api_key="secret-key",
        metronix_mcp_url="http://localhost:8000/mcp",
        metronix_api_url="http://localhost:8000",
        workspace_id="LOCOMO",
        chat_api_key="chat-secret",
        chat_base_url="https://api.openai.com/v1",
        chat_model="gpt-4o-mini",
        retrieve_top_k=10,
    )


def test_parse_categories_is_explicit_and_bounded() -> None:
    assert parse_categories("1, 3,5") == {1, 3, 5}
    with pytest.raises(Exception, match="selected from"):
        parse_categories("6")


def test_manifest_records_parity_fields_without_secrets(tmp_path: Path) -> None:
    output = tmp_path / "answers.jsonl"
    entries = [
        {"question_id": "s1-q0001"},
        {"question_id": "s1-q0002"},
    ]
    manifest_file = write_manifest(
        output,
        config=config(),
        categories={1, 2, 3, 4},
        retrieval_mode="flag-off",
        dataset_path=tmp_path / "locomo10.json",
        entries=entries,
    )
    query_set_file = run_manifest.query_set_path(output)

    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    query_set = json.loads(query_set_file.read_text(encoding="utf-8"))
    serialized = json.dumps(data) + json.dumps(query_set)

    assert data["schema_version"] == run_manifest.MANIFEST_SCHEMA_VERSION
    assert data["benchmark"] == "locomo"
    assert data["stack"]["operator_declared_retrieval_mode"] == "flag-off"
    assert data["stack"]["mcp_endpoint_identity"] == "http://localhost:8000/mcp"
    assert data["config"]["categories"] == [1, 2, 3, 4]
    assert data["config"]["top_k"] == 10
    assert data["config"]["agent_id_prefix"] == "locomo"
    assert data["dataset"]["sha256"] == run_benchmark.DATASET_SHA256
    assert data["dataset"]["upstream_ref"] == run_benchmark.UPSTREAM_COMMIT

    # The query-set digest is the machine-checkable "same set of queries".
    assert query_set["question_ids"] == ["s1-q0001", "s1-q0002"]
    assert data["query_set"]["question_ids_sha256"] == query_set["question_ids_sha256"]
    assert query_set["question_ids_sha256"] == run_manifest.question_ids_digest(
        ["s1-q0001", "s1-q0002"]
    )

    assert "secret-key" not in serialized
    assert "chat-secret" not in serialized


def test_build_run_artifacts_manifest_and_query_set_agree(tmp_path: Path) -> None:
    entries = [{"question_id": f"s-q{n:04d}"} for n in range(5)]
    manifest, query_set = build_run_artifacts(
        config=config(),
        categories={2, 4},
        retrieval_mode="flag-on",
        entries=entries,
        run_id="run-abc",
        workspace_reset="reset",
        stack_snapshot={"qdrant": "connected"},
    )
    assert manifest["run_id"] == "run-abc"
    assert manifest["dataset"]["question_count"] == 5
    assert manifest["query_set"] == run_manifest.query_set_summary(query_set)
    assert query_set["selector"] == {"categories": [2, 4]}
    assert manifest["stack"]["workspace_reset"] == "reset"
    assert manifest["stack"]["probe"] == {"qdrant": "connected"}
    assert manifest["config"]["chat_temperature"] == run_benchmark.CHAT_TEMPERATURE
    assert manifest["config"]["chat_max_tokens"] == run_benchmark.CHAT_MAX_TOKENS


def test_run_derives_a_run_scoped_agent_prefix_and_resumes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry = {
        "question_id": "sample-q0001",
        "sample_id": "sample",
        "category": 2,
        "question": "When?",
        "answer": "Tomorrow",
        "evidence": [],
    }
    monkeypatch.setattr(run_benchmark, "load_dataset", lambda _: [{}])
    monkeypatch.setattr(run_benchmark, "iter_questions", lambda *_a, **_k: iter([entry]))
    monkeypatch.setattr(run_benchmark, "OpenAI", MagicMock())
    monkeypatch.setattr(
        run_benchmark.stack_probe, "probe_stack", lambda _url: {"probe": "skipped"}
    )
    reset_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        run_benchmark.stack_probe,
        "reset_workspace",
        lambda url, ws: reset_calls.append((url, ws)) or "reset",
    )
    monkeypatch.setattr(
        run_benchmark,
        "process_question",
        MagicMock(return_value=("Tomorrow", {"retrieved_count": 0})),
    )
    output = tmp_path / "answers.jsonl"

    run_benchmark.run(
        config=config(),
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=False,
        retrieval_mode="flag-off",
        reset_workspace=True,
    )

    manifest_1 = json.loads(run_manifest.manifest_path(output).read_text(encoding="utf-8"))
    prefix = manifest_1["config"]["agent_id_prefix"]
    run_id = manifest_1["run_id"]
    assert prefix == f"locomo-flag-off-{run_id[:8]}"
    assert manifest_1["stack"]["workspace_reset"] == "reset"
    assert manifest_1["stack"]["probe"] == {"probe": "skipped"}
    assert reset_calls == [("http://localhost:8000", "LOCOMO")]

    # A resume (no --force) must reuse the same namespace, not mint a new one.
    run_benchmark.run(
        config=config(),
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=False,
        retrieval_mode="flag-off",
    )
    manifest_2 = json.loads(run_manifest.manifest_path(output).read_text(encoding="utf-8"))
    assert manifest_2["run_id"] == run_id
    assert manifest_2["config"]["agent_id_prefix"] == prefix


def _base_entry(question_id: str) -> dict:
    return {
        "question_id": question_id,
        "sample_id": "sample",
        "category": 2,
        "question": "When?",
        "answer": "Tomorrow",
        "evidence": [],
    }


def _run_stubbed(monkeypatch: pytest.MonkeyPatch, entries: list[dict], **run_kwargs) -> None:
    monkeypatch.setattr(run_benchmark, "load_dataset", lambda _: [{}])
    monkeypatch.setattr(run_benchmark, "iter_questions", lambda *_a, **_k: iter(list(entries)))
    monkeypatch.setattr(run_benchmark, "OpenAI", MagicMock())
    monkeypatch.setattr(run_benchmark.stack_probe, "probe_stack", lambda _url: {})
    monkeypatch.setattr(run_benchmark.stack_probe, "reset_workspace", lambda _url, _ws: "reset")
    monkeypatch.setattr(
        run_benchmark,
        "process_question",
        MagicMock(return_value=("Tomorrow", {"retrieved_count": 0})),
    )
    run_benchmark.run(**run_kwargs)


def test_resume_with_changed_chat_model_is_rejected_on_completed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A finished run's answers must not be relabeled by a later, differently-configured run."""
    entries = [_base_entry("sample-q0001")]
    output = tmp_path / "answers.jsonl"

    _run_stubbed(
        monkeypatch,
        entries,
        config=config(),
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=False,
        retrieval_mode="flag-off",
    )
    original_manifest = run_manifest.manifest_path(output).read_text(encoding="utf-8")
    assert run_benchmark.load_completed_ids(output) == {"sample-q0001"}

    changed_config = dataclasses.replace(config(), chat_model="gpt-4o")
    with pytest.raises(run_manifest.ManifestMismatchError, match="chat_model"):
        run_benchmark.run(
            config=changed_config,
            dataset_path=tmp_path / "locomo10.json",
            output_path=output,
            categories={2},
            max_questions=None,
            force=False,
            retrieval_mode="flag-off",
        )

    assert run_manifest.manifest_path(output).read_text(encoding="utf-8") == original_manifest


def test_resume_with_changed_retrieval_mode_is_rejected_on_partial_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partially-completed run must not silently mix configurations under one manifest."""
    entries = [_base_entry("sample-q0001"), _base_entry("sample-q0002")]
    entries[1]["question_id"] = "sample-q0002"
    output = tmp_path / "answers.jsonl"

    _run_stubbed(
        monkeypatch,
        entries,
        config=config(),
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=False,
        retrieval_mode="flag-off",
    )
    # Simulate a genuinely partial run: only the first question actually completed.
    lines = output.read_text(encoding="utf-8").splitlines()
    output.write_text(lines[0] + "\n", encoding="utf-8")
    assert run_benchmark.load_completed_ids(output) == {"sample-q0001"}
    original_manifest = run_manifest.manifest_path(output).read_text(encoding="utf-8")

    changed_config = dataclasses.replace(config(), chat_model="gpt-4o")
    with pytest.raises(run_manifest.ManifestMismatchError):
        run_benchmark.run(
            config=changed_config,
            dataset_path=tmp_path / "locomo10.json",
            output_path=output,
            categories={2},
            max_questions=None,
            force=False,
            retrieval_mode="flag-on",
        )

    assert run_manifest.manifest_path(output).read_text(encoding="utf-8") == original_manifest
    assert run_benchmark.load_completed_ids(output) == {"sample-q0001"}


def test_resume_with_force_bypasses_the_compatibility_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--force starts a fresh run/namespace, so a settings change is expected, not an error."""
    entries = [_base_entry("sample-q0001")]
    output = tmp_path / "answers.jsonl"

    _run_stubbed(
        monkeypatch,
        entries,
        config=config(),
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=False,
        retrieval_mode="flag-off",
    )
    changed_config = dataclasses.replace(config(), chat_model="gpt-4o")

    _run_stubbed(
        monkeypatch,
        entries,
        config=changed_config,
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=True,
        retrieval_mode="flag-on",
    )  # must not raise

    m2 = json.loads(run_manifest.manifest_path(output).read_text(encoding="utf-8"))
    assert m2["config"]["chat_model"] == "gpt-4o"


def test_chat_complete_retries_an_empty_model_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty provider completions must not become scored benchmark failures."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="length")
            ]
        ),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="7 May 2023"))]),
    ]
    monkeypatch.setattr("backoff._sync.time.sleep", lambda _: None)

    answer = chat_complete(client, model="test-model", message="When?")

    assert answer == "7 May 2023"
    assert client.chat.completions.create.call_count == 2


def test_chat_complete_reports_empty_completion_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal empty-answer failures must retain safe provider diagnostics."""
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="length")]
    )
    monkeypatch.setattr("backoff._sync.time.sleep", lambda _: None)

    with pytest.raises(ValueError, match="finish_reason=length"):
        chat_complete(client, model="test-model", message="When?")


def test_run_records_safe_empty_completion_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exhausted empty-answer retries must remain diagnosable without prompt content."""
    entry = {
        "question_id": "sample-q0001",
        "sample_id": "sample",
        "category": 2,
        "question": "When?",
        "answer": "Tomorrow",
        "evidence": [],
    }
    monkeypatch.setattr(run_benchmark, "load_dataset", lambda _: [{}])
    monkeypatch.setattr(run_benchmark, "iter_questions", lambda *_args, **_kwargs: iter([entry]))
    monkeypatch.setattr(
        run_benchmark,
        "process_question",
        MagicMock(side_effect=run_benchmark.EmptyChatCompletionError("length")),
    )
    monkeypatch.setattr(run_benchmark, "OpenAI", MagicMock())
    monkeypatch.setattr(run_benchmark.stack_probe, "probe_stack", lambda _url: {})
    output = tmp_path / "answers.jsonl"

    run_benchmark.run(
        config=config(),
        dataset_path=tmp_path / "locomo10.json",
        output_path=output,
        categories={2},
        max_questions=None,
        force=False,
        retrieval_mode="flag-off",
    )

    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["hypothesis"] == "Error: EmptyChatCompletionError"
    assert row["error"] == {"type": "empty_chat_completion", "finish_reason": "length"}
