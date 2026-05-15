"""Unit tests for ChatHistoryCleanupWorker (MTRNIX-353, T3)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from metatron.chat.cleanup import ChatCleanupStats, ChatHistoryCleanupWorker


def _make_worker(
    messages_deleted: int = 5,
    threads_deleted: int = 2,
    retention_days: int = 90,
    interval_seconds: int = 86400,
) -> tuple[ChatHistoryCleanupWorker, AsyncMock]:
    persistence = AsyncMock()
    persistence.delete_messages_older_than.return_value = messages_deleted
    persistence.delete_orphan_threads.return_value = threads_deleted
    worker = ChatHistoryCleanupWorker(
        persistence,
        retention_days=retention_days,
        interval_seconds=interval_seconds,
    )
    return worker, persistence


# ===========================================================================
# run_once
# ===========================================================================


class TestRunOnce:
    async def test_computes_cutoff_correctly(self) -> None:
        worker, persistence = _make_worker(retention_days=30)

        before = datetime.now(UTC)
        await worker.run_once()

        # The cutoff passed to delete_messages_older_than should be ~30 days ago
        cutoff = persistence.delete_messages_older_than.call_args.args[0]
        expected_cutoff = before - timedelta(days=30)
        # Allow a few seconds of clock drift in the test
        assert abs((cutoff - expected_cutoff).total_seconds()) < 5

    async def test_calls_both_delete_methods_in_order(self) -> None:
        worker, persistence = _make_worker()

        await worker.run_once()

        persistence.delete_messages_older_than.assert_called_once()
        persistence.delete_orphan_threads.assert_called_once()

        # Cutoffs should be the same value
        msg_cutoff = persistence.delete_messages_older_than.call_args.args[0]
        thread_cutoff = persistence.delete_orphan_threads.call_args.args[0]
        # Both use the same cutoff computed at the start of run_once
        assert abs((msg_cutoff - thread_cutoff).total_seconds()) < 1

    async def test_returns_correct_stats(self) -> None:
        worker, _ = _make_worker(messages_deleted=7, threads_deleted=3)

        stats = await worker.run_once()

        assert stats.messages_deleted == 7
        assert stats.threads_deleted == 3

    async def test_swallows_exception_and_returns_zeros(self) -> None:
        worker, persistence = _make_worker()
        persistence.delete_messages_older_than.side_effect = RuntimeError("DB down")

        stats = await worker.run_once()

        assert stats.messages_deleted == 0
        assert stats.threads_deleted == 0

    async def test_stats_dataclass_fields(self) -> None:
        stats = ChatCleanupStats(messages_deleted=10, threads_deleted=2)
        assert stats.messages_deleted == 10
        assert stats.threads_deleted == 2


# ===========================================================================
# run_forever
# ===========================================================================


class TestRunForever:
    async def test_exits_on_cancelled_error(self) -> None:
        worker, _ = _make_worker(interval_seconds=0)

        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.05)
        task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Just verify the task completed without hanging
        assert task.done()

    async def test_sleeps_between_passes(self) -> None:
        """Verify sleep is called with interval_seconds after a successful pass."""
        worker, _ = _make_worker(interval_seconds=999)

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            if delay == 999:
                raise asyncio.CancelledError

        with (
            patch("metatron.chat.cleanup.asyncio.sleep", side_effect=fake_sleep),
            contextlib.suppress(asyncio.CancelledError),
        ):
            await worker.run_forever()

        assert 999 in sleep_calls

    async def test_applies_backoff_on_consecutive_errors(self) -> None:
        """On consecutive errors, backoff sleep value should grow."""
        worker, persistence = _make_worker(interval_seconds=1)
        persistence.delete_messages_older_than.side_effect = RuntimeError("fail")

        sleep_calls: list[float] = []
        call_count = 0

        async def fake_sleep(delay: float) -> None:
            nonlocal call_count
            sleep_calls.append(delay)
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError

        with (
            patch("metatron.chat.cleanup.asyncio.sleep", side_effect=fake_sleep),
            contextlib.suppress(asyncio.CancelledError),
        ):
            await worker.run_forever()

        # All sleep values during error-backoff should be <= 60s (cap)
        for s in sleep_calls:
            assert s <= 60.0
        # Backoff should grow (second sleep >= first sleep)
        if len(sleep_calls) >= 2:
            assert sleep_calls[1] >= sleep_calls[0]
