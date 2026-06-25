from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BENCH_SCRIPTS = (
    Path(__file__).resolve().parents[4] / "benchmarks" / "longmemeval" / "scripts"
)
sys.path.insert(0, str(BENCH_SCRIPTS))

from env_config import BenchConfig, _parse_env_file, load_dotenv  # noqa: E402


def test_parse_env_file_ignores_comments_and_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        'FOO=bar\n'
        'BAZ="quoted"\n'
        "EMPTY=\n",
        encoding="utf-8",
    )
    values = _parse_env_file(env_file)
    assert values == {"FOO": "bar", "BAZ": "quoted", "EMPTY": ""}


def test_bench_config_fallback_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LME_CHAT_API_KEY", raising=False)
    monkeypatch.delenv("LME_JUDGE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("METRONIX_MCP_API_KEY", "mcp-key")

    config = BenchConfig.from_env(load_files=False)
    assert config.chat_api_key == "openai-key"
    assert config.judge_api_key == "openai-key"
    assert config.workspace_id == "MABENCH"


def test_bench_config_judge_falls_back_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LME_CHAT_API_KEY", "chat-key")
    monkeypatch.delenv("LME_JUDGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = BenchConfig.from_env(load_files=False)
    assert config.judge_api_key == "chat-key"


def test_apply_cli_overrides() -> None:
    base = BenchConfig(
        metronix_mcp_api_key="mcp",
        metronix_mcp_url="http://localhost:8000/mcp",
        metronix_api_url="http://localhost:8000",
        workspace_id="MABENCH",
        chat_api_key="chat",
        chat_base_url="https://api.openai.com/v1",
        chat_model="gpt-4o-mini",
        judge_api_key="judge",
        judge_base_url="https://api.openai.com/v1",
        judge_model="gpt-4o",
        retrieve_top_k=10,
    )
    updated = base.apply_cli_overrides(chat_model="gpt-4o", retrieve_top_k=20)
    assert updated.chat_model == "gpt-4o"
    assert updated.retrieve_top_k == 20
    assert updated.chat_api_key == "chat"


def test_load_dotenv_does_not_override_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LME_CHAT_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("LME_CHAT_API_KEY", "existing")
    for key in list(os.environ):
        if key.startswith("LME_") and key != "LME_CHAT_API_KEY":
            monkeypatch.delenv(key, raising=False)

    from env_config import _parse_env_file as parse_only

    for key, value in parse_only(env_file).items():
        if key not in os.environ:
            os.environ[key] = value

    assert os.environ["LME_CHAT_API_KEY"] == "existing"
