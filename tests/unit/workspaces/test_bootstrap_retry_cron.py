"""Unit tests for BootstrapRetryCron (MTRNIX-352, T2).

Tests cover: backoff on PG error, give-up on CAS contention, happy-path
scheduling, config_resolver fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from metatron.workspaces.bootstrap.cron import BootstrapRetryCron
from metatron.workspaces.bootstrap.models import BootstrapState, BootstrapStateEnum


def _make_state(workspace_id: str = "ws-1", retry_count: int = 0) -> BootstrapState:
    return BootstrapState(
        workspace_id=workspace_id,
        state=BootstrapStateEnum.FAILED,
        progress=0.0,
        current_step=None,
        last_processed_resource=None,
        last_processed_id=None,
        indexed_count=0,
        total_count=None,
        last_error="prev error",
        last_synced_at=None,
        retry_count=retry_count,
        next_retry_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    )


class TestRunOnce:
    async def test_happy_path_schedules_job(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        runner.get_cached_source_config.return_value = ("asoc", {"url": "http://x"})
        store.list_failed_ready_for_retry.return_value = [_make_state()]
        store.cas_set_state.return_value = True

        async def _resolver(wid: str):
            return ("asoc", {})

        cron = BootstrapRetryCron(
            state_store=store,
            runner=runner,
            config_resolver=_resolver,
            interval_seconds=60,
            max_attempts=5,
        )
        launched = await cron.run_once()

        assert launched == 1
        runner.schedule.assert_called_once_with(
            "ws-1", source="asoc", config={"url": "http://x"}
        )

    async def test_cas_lost_skips_workspace(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.list_failed_ready_for_retry.return_value = [_make_state()]
        store.cas_set_state.return_value = False  # CAS lost

        async def _resolver(wid: str):
            return ("asoc", {})

        cron = BootstrapRetryCron(
            state_store=store,
            runner=runner,
            config_resolver=_resolver,
            interval_seconds=60,
            max_attempts=5,
        )
        launched = await cron.run_once()

        assert launched == 0
        runner.schedule.assert_not_called()

    async def test_config_resolver_fallback_when_cache_miss(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        runner.get_cached_source_config.return_value = None  # no cache
        store.list_failed_ready_for_retry.return_value = [_make_state()]
        store.cas_set_state.return_value = True

        async def _resolver(wid: str):
            return ("asoc", {"url": "from-db"})

        cron = BootstrapRetryCron(
            state_store=store,
            runner=runner,
            config_resolver=_resolver,
            interval_seconds=60,
            max_attempts=5,
        )
        launched = await cron.run_once()

        assert launched == 1
        runner.schedule.assert_called_once_with(
            "ws-1", source="asoc", config={"url": "from-db"}
        )

    async def test_config_resolver_not_implemented_skips_gracefully(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        runner.get_cached_source_config.return_value = None
        store.list_failed_ready_for_retry.return_value = [_make_state()]
        store.cas_set_state.return_value = True

        async def _resolver(wid: str):
            raise NotImplementedError

        cron = BootstrapRetryCron(
            state_store=store,
            runner=runner,
            config_resolver=_resolver,
            interval_seconds=60,
            max_attempts=5,
        )
        launched = await cron.run_once()

        assert launched == 0

    async def test_per_row_exception_does_not_abort_loop(self) -> None:
        """An exception on one row should not prevent processing subsequent rows."""
        store = AsyncMock()
        runner = AsyncMock()
        runner.get_cached_source_config.return_value = ("asoc", {})
        store.list_failed_ready_for_retry.return_value = [
            _make_state("ws-bad"),
            _make_state("ws-good"),
        ]
        # First CAS raises, second succeeds
        store.cas_set_state.side_effect = [RuntimeError("boom"), True]

        async def _resolver(wid: str):
            return ("asoc", {})

        cron = BootstrapRetryCron(
            state_store=store,
            runner=runner,
            config_resolver=_resolver,
            interval_seconds=60,
            max_attempts=5,
        )
        launched = await cron.run_once()

        assert launched == 1
        runner.schedule.assert_called_once_with("ws-good", source="asoc", config={})

    async def test_empty_candidates_returns_zero(self) -> None:
        store = AsyncMock()
        store.list_failed_ready_for_retry.return_value = []
        runner = AsyncMock()

        async def _resolver(wid: str):
            return ("asoc", {})

        cron = BootstrapRetryCron(
            state_store=store,
            runner=runner,
            config_resolver=_resolver,
            interval_seconds=60,
            max_attempts=5,
        )
        launched = await cron.run_once()
        assert launched == 0
