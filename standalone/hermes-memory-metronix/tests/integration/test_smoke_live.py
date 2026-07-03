from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from metronix import MetronixMemoryProvider
from metronix.client import MetronixClient

pytestmark = pytest.mark.integration


class InlineThread:
    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _integration_enabled() -> bool:
    return os.environ.get("RUN_INTEGRATION_TESTS", "").strip() == "1"


@pytest.fixture
def live_config_or_skip(monkeypatch, tmp_path: Path) -> dict[str, str]:
    if not _integration_enabled():
        pytest.skip("integration smoke requires RUN_INTEGRATION_TESTS=1")

    base_url = os.environ.get("METRONIX_BASE_URL", "").strip()
    workspace_id = os.environ.get("METRONIX_WORKSPACE_ID", "").strip()
    auth_token = os.environ.get("METRONIX_AUTH_TOKEN", "").strip()
    email = os.environ.get("METRONIX_EMAIL", "").strip()
    password = os.environ.get("METRONIX_PASSWORD", "").strip()

    if not base_url or not workspace_id:
        pytest.skip("integration smoke requires METRONIX_BASE_URL and METRONIX_WORKSPACE_ID")
    if not auth_token and not (email and password):
        pytest.skip(
            "integration smoke requires a REST token (JWT/personal API key) "
            "via METRONIX_AUTH_TOKEN, or METRONIX_EMAIL + METRONIX_PASSWORD"
        )

    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    monkeypatch.setattr("metronix._get_hermes_home", lambda: hermes_home)

    return {
        "base_url": base_url,
        "workspace_id": workspace_id,
        "auth_token": auth_token,
        "email": email,
        "password": password,
        "hermes_home": str(hermes_home),
    }


def test_live_ping_smoke(live_config_or_skip: dict[str, str]) -> None:
    client = MetronixClient(
        base_url=live_config_or_skip["base_url"],
        workspace_id=live_config_or_skip["workspace_id"],
        auth_token=live_config_or_skip["auth_token"],
        email=live_config_or_skip["email"],
        password=live_config_or_skip["password"],
    )

    payload = client.ping()

    assert payload["status"] == "ok"


def test_live_provider_write_and_prefetch_smoke(
    monkeypatch,
    live_config_or_skip: dict[str, str],
) -> None:
    unique = uuid4().hex[:12]
    content = f"smoke preference {unique}"
    record_id = ""

    client = MetronixClient(
        base_url=live_config_or_skip["base_url"],
        workspace_id=live_config_or_skip["workspace_id"],
        auth_token=live_config_or_skip["auth_token"],
        email=live_config_or_skip["email"],
        password=live_config_or_skip["password"],
    )

    provider = MetronixMemoryProvider()
    monkeypatch.setattr("metronix.threading.Thread", InlineThread)
    monkeypatch.setenv("METRONIX_BASE_URL", live_config_or_skip["base_url"])
    monkeypatch.setenv("METRONIX_WORKSPACE_ID", live_config_or_skip["workspace_id"])
    if live_config_or_skip["auth_token"]:
        monkeypatch.setenv("METRONIX_AUTH_TOKEN", live_config_or_skip["auth_token"])
    if live_config_or_skip["email"]:
        monkeypatch.setenv("METRONIX_EMAIL", live_config_or_skip["email"])
    if live_config_or_skip["password"]:
        monkeypatch.setenv("METRONIX_PASSWORD", live_config_or_skip["password"])

    provider.initialize(
        session_id=f"smoke-session-{unique}",
        hermes_home=live_config_or_skip["hermes_home"],
        agent_identity="smoke-agent",
    )

    try:
        provider.on_memory_write(
            "add",
            "user",
            content,
            metadata={"source": "integration_smoke"},
        )
        results = client.search_memory(query=unique, top_k=10, agent_id="smoke-agent")
        matching = [
            item for item in results
            if unique in str((item.get("record") or {}).get("content", ""))
        ]
        assert matching, f"expected to find smoke memory for token {unique}"
        record = matching[0]["record"]
        record_id = str(record["id"])

        prefetched = provider.prefetch(unique)
        assert "<memory-context>" in prefetched
        assert content in prefetched
    finally:
        if record_id:
            client.delete_memory(record_id)
