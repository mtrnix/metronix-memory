"""Unit tests for BootstrapJob (MTRNIX-352, T2).

Happy path, error-on-fetch, error-on-ingest, give-up after max_retries.
No live DB or connector needed — everything is mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.workspaces.bootstrap.job import BootstrapJob
from metatron.workspaces.bootstrap.models import BootstrapState, BootstrapStateEnum


def _make_state(**kwargs: object) -> BootstrapState:
    defaults = dict(
        workspace_id="ws-1",
        state=BootstrapStateEnum.BOOTSTRAPPING,
        progress=0.0,
        current_step=None,
        last_processed_resource=None,
        last_processed_id=None,
        indexed_count=0,
        total_count=None,
        last_error=None,
        last_synced_at=None,
        retry_count=0,
        next_retry_at=None,
        updated_at=datetime(2026, 5, 15, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return BootstrapState(**defaults)


def _make_job(
    connector: AsyncMock,
    store: AsyncMock,
    ingest_fn: AsyncMock,
    *,
    max_retries: int = 3,
    backoff_base: float = 60.0,
) -> BootstrapJob:
    return BootstrapJob(
        "ws-1",
        connector=connector,
        state_store=store,
        ingest_fn=ingest_fn,
        max_retries=max_retries,
        backoff_base_seconds=backoff_base,
    )


class TestBootstrapJobHappyPath:
    async def test_run_success_transitions_to_ready(self) -> None:
        connector = AsyncMock()
        connector.fetch.return_value = [MagicMock(), MagicMock()]  # 2 docs
        store = AsyncMock()
        store.get.return_value = _make_state()
        ingest_fn = AsyncMock()

        job = _make_job(connector, store, ingest_fn)
        await job.run()

        ingest_fn.assert_called_once()
        store.set_state.assert_called_once_with(
            "ws-1",
            state=BootstrapStateEnum.READY,
            clear_error=True,
        )

    async def test_run_missing_state_row_exits_early(self) -> None:
        """If no bootstrap_state row exists, job exits without error."""
        connector = AsyncMock()
        store = AsyncMock()
        store.get.return_value = None  # no row
        ingest_fn = AsyncMock()

        job = _make_job(connector, store, ingest_fn)
        await job.run()

        ingest_fn.assert_not_called()


class TestBootstrapJobFailure:
    async def test_connector_error_calls_set_failed(self) -> None:
        connector = AsyncMock()
        connector.fetch.side_effect = RuntimeError("network error")
        store = AsyncMock()
        store.get.side_effect = [
            _make_state(retry_count=0),
            _make_state(retry_count=0),  # second get in error handler
        ]
        ingest_fn = AsyncMock()

        job = _make_job(connector, store, ingest_fn)
        await job.run()

        store.set_failed.assert_called_once()
        call_kwargs = store.set_failed.call_args.kwargs
        assert call_kwargs["last_error"] == "network error"
        assert call_kwargs["next_retry_at"] is not None  # retry scheduled

    async def test_ingest_error_calls_set_failed(self) -> None:
        connector = AsyncMock()
        connector.fetch.return_value = [MagicMock()]
        store = AsyncMock()
        store.get.side_effect = [
            _make_state(retry_count=0),
            _make_state(retry_count=0),
        ]
        ingest_fn = AsyncMock(side_effect=RuntimeError("ingest boom"))

        job = _make_job(connector, store, ingest_fn, max_retries=3)
        await job.run()

        store.set_failed.assert_called_once()

    async def test_give_up_after_max_retries_sets_none_next_retry(self) -> None:
        """When retry_count reaches max_retries, next_retry_at must be None (give up)."""
        connector = AsyncMock()
        connector.fetch.side_effect = RuntimeError("boom")
        store = AsyncMock()
        # retry_count=2, max_retries=3 → after increment → 3 == max → give up
        store.get.side_effect = [
            _make_state(retry_count=2),
            _make_state(retry_count=2),
        ]
        ingest_fn = AsyncMock()

        job = _make_job(connector, store, ingest_fn, max_retries=3)
        await job.run()

        call_kwargs = store.set_failed.call_args.kwargs
        assert call_kwargs["next_retry_at"] is None  # give up


class TestComputeNextRetry:
    def test_first_attempt(self) -> None:
        job = BootstrapJob(
            "ws-1",
            connector=MagicMock(),
            state_store=MagicMock(),
            ingest_fn=MagicMock(),
            max_retries=5,
            backoff_base_seconds=60.0,
        )
        next_r = job._compute_next_retry(1)
        assert next_r is not None
        # delay should be ~60s
        now = datetime.now(UTC)
        delta = (next_r - now).total_seconds()
        assert 55 <= delta <= 65

    def test_second_attempt(self) -> None:
        job = BootstrapJob(
            "ws-1",
            connector=MagicMock(),
            state_store=MagicMock(),
            ingest_fn=MagicMock(),
            max_retries=5,
            backoff_base_seconds=60.0,
        )
        next_r = job._compute_next_retry(2)
        assert next_r is not None
        now = datetime.now(UTC)
        delta = (next_r - now).total_seconds()
        assert 115 <= delta <= 125

    def test_exceeds_max_retries_returns_none(self) -> None:
        job = BootstrapJob(
            "ws-1",
            connector=MagicMock(),
            state_store=MagicMock(),
            ingest_fn=MagicMock(),
            max_retries=3,
            backoff_base_seconds=60.0,
        )
        assert job._compute_next_retry(3) is None
        assert job._compute_next_retry(100) is None

    def test_cap_applied(self) -> None:
        job = BootstrapJob(
            "ws-1",
            connector=MagicMock(),
            state_store=MagicMock(),
            ingest_fn=MagicMock(),
            max_retries=100,
            backoff_base_seconds=60.0,
            backoff_cap_seconds=3600.0,
        )
        # Very large retry_count should be capped at 3600s
        next_r = job._compute_next_retry(50)
        assert next_r is not None
        now = datetime.now(UTC)
        delta = (next_r - now).total_seconds()
        assert delta <= 3605  # cap + small fuzz
