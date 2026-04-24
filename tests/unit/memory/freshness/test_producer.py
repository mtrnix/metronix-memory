"""Unit tests for the freshness producer hook (MTRNIX-304)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from metatron.core.config import get_settings
from metatron.memory.freshness import producer
from metatron.memory.freshness.coordination import CoordinationStore


@pytest.fixture(autouse=True)
def _reset_default_store() -> None:
    """Ensure the lazy singleton does not leak across tests."""
    producer._reset_default_for_tests()


@pytest.fixture
def disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", False)


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)


class TestProducer:
    async def test_noop_when_flag_off(
        self, disabled: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the producer accidentally touched Redis, this would explode.
        monkeypatch.setattr(
            producer,
            "_build_default_coordination",
            lambda: pytest.fail("default store must not be constructed"),
        )
        await producer.enqueue_if_enabled("ws1", "rec1")

    async def test_lpushes_when_flag_on(self, enabled: None) -> None:
        redis = AsyncMock()
        store = CoordinationStore(redis=redis)

        await producer.enqueue_if_enabled(
            "ws1",
            "rec1",
            "content_changed",
            coordination=store,
        )

        redis.lpush.assert_awaited_once()
        key, payload = redis.lpush.await_args.args
        assert key == "freshness:development:queue:ws1"
        assert "content_changed" in payload
        assert "rec1" in payload

    async def test_forwards_payload(self, enabled: None) -> None:
        redis = AsyncMock()
        store = CoordinationStore(redis=redis)

        await producer.enqueue_if_enabled(
            "ws1",
            "rec1",
            "knowledge_changed",
            coordination=store,
            payload={"source": "mcp.memory_store"},
        )

        args = redis.lpush.await_args.args
        assert "mcp.memory_store" in args[1]

    async def test_swallows_redis_errors(self, enabled: None) -> None:
        redis = AsyncMock()
        redis.lpush.side_effect = ConnectionError("redis down")
        store = CoordinationStore(redis=redis)

        # Must NOT raise — memory_store cannot break because freshness is
        # misbehaving.
        await producer.enqueue_if_enabled("ws1", "rec1", coordination=store)

    async def test_missing_ids_are_dropped(self, enabled: None) -> None:
        redis = AsyncMock()
        store = CoordinationStore(redis=redis)

        await producer.enqueue_if_enabled("", "rec1", coordination=store)
        await producer.enqueue_if_enabled("ws1", "", coordination=store)

        redis.lpush.assert_not_awaited()
