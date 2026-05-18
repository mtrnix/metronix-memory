"""In-memory token bucket rate limiter for ASOC chat (MTRNIX-354, T4).

A single ``InMemoryTokenBucket`` instance is created at app startup and shared
across all requests (but NOT across worker replicas — each process has its own
bucket, which is acceptable given the short token refill interval).

LRU-style eviction drops the oldest 25 % of entries when the soft cap of 10 000
user IDs is exceeded, keeping memory bounded in a multi-user deployment.
"""

from __future__ import annotations

import asyncio
import time


class InMemoryTokenBucket:
    """Async token bucket rate limiter — one bucket per ``user_id``.

    Each user starts with a full bucket (``capacity`` tokens) and tokens refill
    continuously at ``rate_per_min / 60`` tokens per second.  A single request
    consumes one token.  When the bucket is empty ``acquire`` returns ``False``
    and the caller must reject the request.

    Args:
        rate_per_min: Sustained request rate in requests per minute.
        capacity: Burst capacity in tokens.  Defaults to ``rate_per_min``
            (burst == 1 minute of sustained rate).
    """

    _EVICTION_CAP = 10_000

    def __init__(self, rate_per_min: int, capacity: int | None = None) -> None:
        self.rate_per_sec: float = rate_per_min / 60.0
        self.capacity: float = float(capacity if capacity is not None else rate_per_min)
        # user_id -> (tokens_remaining, last_refill_monotonic_ts)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str) -> bool:
        """Try to consume one token for *user_id*.

        Returns:
            ``True`` if the token was consumed (request allowed).
            ``False`` if the bucket is empty (request should be rejected).
        """
        async with self._lock:
            now = time.monotonic()
            tokens, last = self._buckets.get(user_id, (self.capacity, now))

            # Refill tokens based on elapsed time.
            elapsed = now - last
            tokens = min(self.capacity, tokens + elapsed * self.rate_per_sec)

            if tokens < 1.0:
                self._buckets[user_id] = (tokens, now)
                return False

            self._buckets[user_id] = (tokens - 1.0, now)

            # LRU-style eviction when the soft cap is exceeded.
            if len(self._buckets) > self._EVICTION_CAP:
                self._evict()

            return True

    def _evict(self) -> None:
        """Drop the oldest 25 % of buckets (by last-refill timestamp).

        Must be called while holding ``_lock``.
        """
        sorted_items = sorted(self._buckets.items(), key=lambda kv: kv[1][1])
        drop_count = max(1, len(sorted_items) // 4)
        for key, _ in sorted_items[:drop_count]:
            del self._buckets[key]
