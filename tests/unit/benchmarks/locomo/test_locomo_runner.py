from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.locomo.scripts.env_config import BenchConfig
from benchmarks.locomo.scripts.run_benchmark import parse_categories, write_manifest


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
