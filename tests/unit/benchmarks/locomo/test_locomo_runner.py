from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from benchmarks.locomo.scripts import run_benchmark
from benchmarks.locomo.scripts.env_config import BenchConfig
from benchmarks.locomo.scripts.run_benchmark import chat_complete, parse_categories, write_manifest


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
    manifest = write_manifest(
        output,
        config=config(),
        categories={1, 2, 3, 4},
        retrieval_mode="flag-off",
        dataset_path=tmp_path / "locomo10.json",
    )

    data = json.loads(manifest.read_text(encoding="utf-8"))
    serialized = json.dumps(data)
    assert data["operator_declared_retrieval_mode"] == "flag-off"
    assert data["categories"] == [1, 2, 3, 4]
    assert data["top_k"] == 10
    assert "secret-key" not in serialized
    assert "chat-secret" not in serialized


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
