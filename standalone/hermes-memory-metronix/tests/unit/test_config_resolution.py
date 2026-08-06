from __future__ import annotations

import json
from pathlib import Path

from metronix import MetronixMemoryProvider


def test_is_available_false_without_required_fields(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    provider = MetronixMemoryProvider()

    assert provider.is_available() is False


def test_is_available_true_with_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("METRONIX_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("METRONIX_WORKSPACE_ID", "MTRNIX")
    monkeypatch.setenv("METRONIX_AUTH_TOKEN", "secret")

    provider = MetronixMemoryProvider()

    assert provider.is_available() is True


def test_is_available_true_with_login(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("METRONIX_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("METRONIX_WORKSPACE_ID", "MTRNIX")
    monkeypatch.setenv("METRONIX_EMAIL", "admin@example.com")
    monkeypatch.setenv("METRONIX_PASSWORD", "password")

    provider = MetronixMemoryProvider()

    assert provider.is_available() is True


def test_save_config_writes_metronix_json(tmp_path: Path):
    provider = MetronixMemoryProvider()

    provider.save_config({"base_url": "http://localhost:8000"}, str(tmp_path))

    payload = json.loads((tmp_path / "metronix.json").read_text(encoding="utf-8"))
    assert payload["base_url"] == "http://localhost:8000"


def test_load_config_prefers_file_for_non_secret_config(monkeypatch, tmp_path: Path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (hermes_home / "metronix.json").write_text(
        json.dumps(
            {
                "base_url": "http://file.example",
                "workspace_id": "WS_FILE",
                "prefetch_top_k": 11,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("METRONIX_BASE_URL", "http://env.example")
    monkeypatch.setenv("METRONIX_WORKSPACE_ID", "WS_ENV")
    monkeypatch.setenv("METRONIX_AUTH_TOKEN", "secret")
    monkeypatch.setattr("metronix._get_hermes_home", lambda: hermes_home)

    provider = MetronixMemoryProvider()
    cfg = provider._load_config()

    assert cfg["base_url"] == "http://file.example"
    assert cfg["workspace_id"] == "WS_FILE"
    assert cfg["prefetch_top_k"] == 11
    assert cfg["auth_token"] == "secret"


def test_initialize_prefers_runtime_agent_identity_over_default(monkeypatch, tmp_path: Path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (hermes_home / "metronix.json").write_text(
        json.dumps(
            {
                "base_url": "http://localhost:8000",
                "workspace_id": "MTRNIX",
                "auth_token": "secret",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("metronix._get_hermes_home", lambda: hermes_home)

    provider = MetronixMemoryProvider()
    provider.initialize("sess-1", agent_identity="smoke-agent")

    assert provider._agent_id == "smoke-agent"


def test_initialize_prefers_explicit_configured_agent_id(monkeypatch, tmp_path: Path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (hermes_home / "metronix.json").write_text(
        json.dumps(
            {
                "base_url": "http://localhost:8000",
                "workspace_id": "MTRNIX",
                "auth_token": "secret",
                "agent_id": "configured-agent",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("metronix._get_hermes_home", lambda: hermes_home)

    provider = MetronixMemoryProvider()
    provider.initialize("sess-1", agent_identity="smoke-agent")

    assert provider._agent_id == "configured-agent"
