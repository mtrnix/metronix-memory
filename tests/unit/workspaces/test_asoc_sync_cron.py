"""Unit tests for AsocSyncCron (MTRNIX-357, T7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.workspaces.bootstrap.models import BootstrapState, BootstrapStateEnum
from metatron.workspaces.bootstrap.sync_cron import AsocSyncCron

_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


def _make_state(
    workspace_id: str = "asoc-prod-proj-1",
    *,
    last_synced_at: datetime | None = None,
    last_processed_resource: str | None = None,
    last_processed_id: str | None = None,
) -> BootstrapState:
    return BootstrapState(
        workspace_id=workspace_id,
        state=BootstrapStateEnum.READY,
        progress=1.0,
        current_step=None,
        last_processed_resource=last_processed_resource,
        last_processed_id=last_processed_id,
        indexed_count=10,
        total_count=10,
        last_error=None,
        last_synced_at=last_synced_at,
        retry_count=0,
        next_retry_at=None,
        updated_at=_NOW,
    )


def _make_cron(
    *,
    list_ready_workspaces=None,
    connector_factory=None,
    ingest_fn=None,
    touch_last_synced_at=None,
    interval_seconds: int = 900,
    max_concurrent: int = 3,
):
    store = MagicMock()
    store.list_ready_workspaces = list_ready_workspaces or AsyncMock(return_value=[])
    store.touch_last_synced_at = touch_last_synced_at or AsyncMock(return_value=None)
    return AsocSyncCron(
        state_store=store,
        connector_factory=connector_factory or AsyncMock(),
        ingest_fn=ingest_fn or AsyncMock(),
        interval_seconds=interval_seconds,
        max_concurrent_workspaces=max_concurrent,
    ), store


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------


class TestRunOnce:
    async def test_empty_workspaces_returns_zero_no_connector_calls(self) -> None:
        connector_factory = AsyncMock()
        ingest_fn = AsyncMock()
        cron, _ = _make_cron(connector_factory=connector_factory, ingest_fn=ingest_fn)

        result = await cron.run_once()

        assert result == {"workspaces": 0, "succeeded": 0, "failed": 0}
        connector_factory.assert_not_called()
        ingest_fn.assert_not_called()

    async def test_syncs_one_workspace_happy(self) -> None:
        ws = _make_state(last_synced_at=_NOW)
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=[{"doc": "x"}])
        connector_factory = AsyncMock(return_value=connector)
        ingest_fn = AsyncMock()
        touch = AsyncMock()
        cron, store = _make_cron(
            list_ready_workspaces=AsyncMock(return_value=[ws]),
            connector_factory=connector_factory,
            ingest_fn=ingest_fn,
            touch_last_synced_at=touch,
        )

        result = await cron.run_once()

        assert result == {"workspaces": 1, "succeeded": 1, "failed": 0}
        connector_factory.assert_awaited_once_with(ws.workspace_id)
        connector.fetch.assert_awaited_once_with(ws.workspace_id, since=_NOW)
        ingest_fn.assert_awaited_once_with([{"doc": "x"}], ws.workspace_id)
        touch.assert_awaited_once()

    async def test_passes_resume_hints_when_present(self) -> None:
        ws = _make_state(
            last_synced_at=_NOW,
            last_processed_resource="issue",
            last_processed_id="abc-123",
        )
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=[])
        cron, _ = _make_cron(
            list_ready_workspaces=AsyncMock(return_value=[ws]),
            connector_factory=AsyncMock(return_value=connector),
        )

        await cron.run_once()

        connector.fetch.assert_awaited_once_with(
            ws.workspace_id,
            since=_NOW,
            after_resource="issue",
            after_id="abc-123",
        )

    async def test_no_resume_hints_when_absent(self) -> None:
        ws = _make_state(last_synced_at=_NOW)  # no resume fields
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=[])
        cron, _ = _make_cron(
            list_ready_workspaces=AsyncMock(return_value=[ws]),
            connector_factory=AsyncMock(return_value=connector),
        )

        await cron.run_once()

        connector.fetch.assert_awaited_once_with(ws.workspace_id, since=_NOW)

    async def test_skips_ingest_when_no_documents(self) -> None:
        ws = _make_state()
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=[])
        ingest_fn = AsyncMock()
        cron, _ = _make_cron(
            list_ready_workspaces=AsyncMock(return_value=[ws]),
            connector_factory=AsyncMock(return_value=connector),
            ingest_fn=ingest_fn,
        )

        result = await cron.run_once()

        assert result["succeeded"] == 1
        ingest_fn.assert_not_called()

    async def test_per_workspace_failure_isolated(self) -> None:
        ws_ok = _make_state("ws-ok")
        ws_bad = _make_state("ws-bad")

        async def factory(wid: str) -> object:
            if wid == "ws-bad":
                raise RuntimeError("boom")
            c = MagicMock()
            c.fetch = AsyncMock(return_value=[])
            return c

        cron, _ = _make_cron(
            list_ready_workspaces=AsyncMock(return_value=[ws_ok, ws_bad]),
            connector_factory=factory,
        )

        result = await cron.run_once()

        assert result == {"workspaces": 2, "succeeded": 1, "failed": 1}

    async def test_returns_zero_when_list_query_fails(self) -> None:
        connector_factory = AsyncMock()
        cron, _ = _make_cron(
            list_ready_workspaces=AsyncMock(side_effect=RuntimeError("db down")),
            connector_factory=connector_factory,
        )

        result = await cron.run_once()

        assert result == {"workspaces": 0, "succeeded": 0, "failed": 0}
        connector_factory.assert_not_called()

    async def test_semaphore_bounds_concurrency(self) -> None:
        """Semaphore=2 — never more than 2 connector_factory calls in flight."""
        in_flight = 0
        max_in_flight = 0
        gate = asyncio.Event()

        async def factory(wid: str) -> object:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await gate.wait()
            in_flight -= 1
            c = MagicMock()
            c.fetch = AsyncMock(return_value=[])
            return c

        workspaces = [_make_state(f"ws-{i}") for i in range(5)]
        cron, _ = _make_cron(
            list_ready_workspaces=AsyncMock(return_value=workspaces),
            connector_factory=factory,
            max_concurrent=2,
        )

        task = asyncio.create_task(cron.run_once())
        # Let the cron schedule and bound at 2
        for _ in range(20):
            await asyncio.sleep(0)
        assert max_in_flight <= 2
        gate.set()
        await task
        assert max_in_flight == 2


# ---------------------------------------------------------------------------
# run_forever
# ---------------------------------------------------------------------------


class TestRunForever:
    async def test_ticks_until_stop(self) -> None:
        call_count = 0

        async def list_ws() -> list:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                cron.stop()
            return []

        cron, _ = _make_cron(
            list_ready_workspaces=list_ws,
            interval_seconds=0,  # immediate next tick
        )

        await asyncio.wait_for(cron.run_forever(), timeout=2.0)

        assert call_count >= 2

    async def test_backoff_on_consecutive_errors(self) -> None:
        """On tick error, run_forever sleeps with bounded backoff and retries."""
        call_count = 0

        async def list_ws() -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")
            cron.stop()
            return []

        cron, _ = _make_cron(
            list_ready_workspaces=list_ws,
            interval_seconds=0,
        )

        # list_ready_workspaces raising should NOT propagate from run_once,
        # which catches and returns zeros. So run_forever's error path is
        # exercised by making run_once itself raise. Simulate by patching:
        original_run_once = cron.run_once

        async def flaky_run_once() -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("tick error")
            cron.stop()
            return await original_run_once()

        cron.run_once = flaky_run_once  # type: ignore[method-assign]

        await asyncio.wait_for(cron.run_forever(), timeout=10.0)

        # Two ticks executed: first raised, second succeeded and called stop().
        assert call_count >= 2

    async def test_cancel_propagates(self) -> None:
        async def list_ws() -> list:
            await asyncio.sleep(10)  # block forever
            return []

        cron, _ = _make_cron(
            list_ready_workspaces=list_ws,
            interval_seconds=900,
        )

        task = asyncio.create_task(cron.run_forever())
        await asyncio.sleep(0.05)  # give it time to start
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    async def test_stop_sets_event(self) -> None:
        cron, _ = _make_cron()
        assert not cron._stop_event.is_set()
        cron.stop()
        assert cron._stop_event.is_set()
