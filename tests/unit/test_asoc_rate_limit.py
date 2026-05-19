"""Unit tests for InMemoryTokenBucket rate limiter (MTRNIX-354, T4)."""

from __future__ import annotations

import asyncio

from metatron.chat.asoc_rate_limit import InMemoryTokenBucket


class TestInMemoryTokenBucket:
    async def test_first_request_always_allowed(self) -> None:
        bucket = InMemoryTokenBucket(rate_per_min=10)
        result = await bucket.acquire("user-1")
        assert result is True

    async def test_within_rate_limit_allowed(self) -> None:
        bucket = InMemoryTokenBucket(rate_per_min=5)
        for _ in range(5):
            allowed = await bucket.acquire("user-1")
        assert allowed is True

    async def test_exceeding_rate_limit_denied(self) -> None:
        bucket = InMemoryTokenBucket(rate_per_min=2)
        await bucket.acquire("user-1")
        await bucket.acquire("user-1")
        # Third request should be denied
        result = await bucket.acquire("user-1")
        assert result is False

    async def test_different_users_have_separate_buckets(self) -> None:
        bucket = InMemoryTokenBucket(rate_per_min=1)
        await bucket.acquire("user-A")  # exhaust user-A
        result_a = await bucket.acquire("user-A")
        result_b = await bucket.acquire("user-B")

        assert result_a is False  # user-A exhausted
        assert result_b is True   # user-B fresh

    async def test_lru_eviction_at_capacity(self) -> None:
        """When capacity reached (10k), oldest entry is evicted."""
        bucket = InMemoryTokenBucket(rate_per_min=1, capacity=5)
        # Fill capacity with users 0-4
        for i in range(5):
            await bucket.acquire(f"user-{i}")

        # Exhaust user-0
        await bucket.acquire("user-0")

        # Add user-5 — should trigger eviction of oldest entry
        result = await bucket.acquire("user-5")
        assert result is True

    async def test_rate_per_min_respected(self) -> None:
        bucket = InMemoryTokenBucket(rate_per_min=60)
        # 60 per minute means 1 per second — we should allow 60 within a minute
        for _ in range(60):
            result = await bucket.acquire("user-1")
        assert result is True

        # 61st should be denied
        result = await bucket.acquire("user-1")
        assert result is False

    async def test_concurrent_requests_thread_safe(self) -> None:
        """Multiple concurrent acquires for the same user should be safe."""
        bucket = InMemoryTokenBucket(rate_per_min=5)

        async def acquire() -> bool:
            return await bucket.acquire("shared-user")

        results = await asyncio.gather(*[acquire() for _ in range(10)])
        allowed_count = sum(1 for r in results if r)
        denied_count = sum(1 for r in results if not r)

        assert allowed_count <= 5  # at most rate_per_min allowed
        assert allowed_count + denied_count == 10
