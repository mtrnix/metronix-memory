"""Unit tests for env-prefixed freshness keys (MTRNIX-316).

Ensures ``_key_prefix()`` honours ``settings.env`` and that every freshness
key (queue, processing, heartbeat, stage lock, reclaim lock) routes through
it. Backwards-compatible when env is empty.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from metatron.core import config as config_mod
from metatron.freshness import coordination as coord_mod
from metatron.freshness.coordination import (
    CoordinationStore,
    processing_key_for,
    queue_key_for,
)


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    """Force a fresh ``Settings`` each test so env monkeypatching takes effect."""
    config_mod._settings = None
    yield
    config_mod._settings = None


def _make() -> tuple[CoordinationStore, AsyncMock]:
    redis = AsyncMock()
    return CoordinationStore(redis=redis), redis


class TestQueueKey:
    def test_prefixed_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        assert queue_key_for("ws-1") == "freshness:development:queue:ws-1"

    def test_legacy_shape_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Bypass Settings pydantic validator by patching get_settings directly.
        monkeypatch.setattr(coord_mod, "get_settings", lambda: _FakeSettings(env=""))
        assert queue_key_for("ws-1") == "freshness:queue:ws-1"


class TestProcessingKey:
    def test_prefixed_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "staging")
        assert processing_key_for("worker-a") == "freshness:staging:processing:worker-a"

    def test_unprefixed_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coord_mod, "get_settings", lambda: _FakeSettings(env=""))
        assert processing_key_for("worker-a") == "freshness:processing:worker-a"


class TestStageLockKey:
    async def test_stage_lock_prefixed_when_env_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.acquire_lock.return_value = True

        token = await store.acquire_lock("linker", "rec1", ttl=30)

        assert token is not None
        key = redis.acquire_lock.await_args.args[0]
        assert key == "freshness:development:linker:rec1"

    async def test_stage_lock_kb_target_kind_prefixed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.acquire_lock.return_value = True

        await store.acquire_lock("linker", "doc1", ttl=30, target_kind="raw_document")

        key = redis.acquire_lock.await_args.args[0]
        assert key == "freshness:development:linker:raw_document:doc1"

    async def test_stage_lock_legacy_shape_when_env_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(coord_mod, "get_settings", lambda: _FakeSettings(env=""))
        store, redis = _make()
        redis.acquire_lock.return_value = True

        await store.acquire_lock("linker", "rec1", ttl=30)

        key = redis.acquire_lock.await_args.args[0]
        assert key == "freshness:linker:rec1"


class TestListActiveWorkspaces:
    async def test_scans_with_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.scan_keys.return_value = [
            "freshness:development:queue:ws-1",
            "freshness:development:queue:ws-2",
        ]

        ws = await store.list_active_workspaces()

        assert sorted(ws) == ["ws-1", "ws-2"]
        redis.scan_keys.assert_awaited_once_with("freshness:development:queue:*")

    async def test_scans_legacy_shape_when_env_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(coord_mod, "get_settings", lambda: _FakeSettings(env=""))
        store, redis = _make()
        redis.scan_keys.return_value = ["freshness:queue:ws-1"]

        ws = await store.list_active_workspaces()

        assert ws == ["ws-1"]
        redis.scan_keys.assert_awaited_once_with("freshness:queue:*")


class _FakeSettings:
    """Minimal Settings duck-type for tests that need env=''."""

    def __init__(self, env: str) -> None:
        self.env = env
