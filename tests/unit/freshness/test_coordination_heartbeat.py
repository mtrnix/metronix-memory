"""Unit tests for worker heartbeat helpers on ``CoordinationStore`` (PROJ-316)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from metronix.core import config as config_mod
from metronix.freshness.coordination import CoordinationStore


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    config_mod._settings = None
    yield
    config_mod._settings = None


def _make() -> tuple[CoordinationStore, AsyncMock]:
    redis = AsyncMock()
    return CoordinationStore(redis=redis), redis


class TestTickHeartbeat:
    async def test_sets_key_with_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()

        await store.tick_heartbeat("worker-a", ttl=20)

        # Plain SET with TTL (no NX): upsert-set.
        redis.set.assert_awaited_once_with(
            "freshness:development:heartbeat:worker-a",
            "worker-a",
            ttl=20,
        )

    async def test_swallows_redis_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()
        redis.set.side_effect = RuntimeError("redis down")

        # Must not raise — best-effort.
        await store.tick_heartbeat("worker-a", ttl=20)


class TestIsWorkerAlive:
    async def test_returns_true_when_key_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = True

        assert await store.is_worker_alive("worker-a") is True
        redis.exists.assert_awaited_once_with("freshness:development:heartbeat:worker-a")

    async def test_returns_false_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = False

        assert await store.is_worker_alive("worker-a") is False

    async def test_fails_closed_on_redis_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()
        redis.exists.side_effect = RuntimeError("redis down")

        # Fail-closed: treat as dead so reclaim pass retries next iteration.
        assert await store.is_worker_alive("worker-a") is False


class TestReleaseWorker:
    async def test_deletes_heartbeat_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()

        await store.release_worker("worker-a")

        redis.delete.assert_awaited_once_with("freshness:development:heartbeat:worker-a")

    async def test_swallows_redis_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_ENV", "development")
        store, redis = _make()
        redis.delete.side_effect = RuntimeError("redis down")

        # Best-effort — TTL would expire the key anyway.
        await store.release_worker("worker-a")
