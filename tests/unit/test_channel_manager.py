"""Tests for ChannelManager.reconcile_once/reconcile_loop.

A poller whose connection row was removed or disabled out-of-band (direct
SQL, a script — anything that bypasses DELETE/PUT /connections/{id}, which
already call stop_channel themselves) must not run forever. reconcile_once
is the backstop that catches that case.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from metronix.channels.manager import ChannelManager


class _FakeChannel:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _add_running(manager: ChannelManager, connection_id: str) -> _FakeChannel:
    """Simulate a live poller without actually starting a real bot."""
    channel = _FakeChannel()
    manager._running[connection_id] = channel
    manager._tasks[connection_id] = asyncio.create_task(asyncio.sleep(1000))
    return channel


@pytest.fixture
def manager() -> ChannelManager:
    router = AsyncMock()
    store = AsyncMock()
    return ChannelManager(router=router, store=store)


async def test_reconcile_once_stops_orphan_when_row_missing(manager: ChannelManager) -> None:
    """Row no longer exists in the DB at all -> the poller is stopped."""
    channel = _add_running(manager, "c1")
    manager._store.list_connections.return_value = []

    stopped = await manager.reconcile_once("fernet", "ws_default")

    assert stopped == ["c1"]
    assert "c1" not in manager.running_ids
    assert channel.stopped is True


async def test_reconcile_once_stops_orphan_when_disabled(manager: ChannelManager) -> None:
    """Row still exists but was disabled out-of-band -> the poller is stopped."""
    _add_running(manager, "c1")
    manager._store.list_connections.return_value = [{"id": "c1", "enabled": False}]

    stopped = await manager.reconcile_once("fernet", "ws_default")

    assert stopped == ["c1"]
    assert "c1" not in manager.running_ids


async def test_reconcile_once_leaves_healthy_channel_running(manager: ChannelManager) -> None:
    """Row exists and is enabled -> nothing is stopped."""
    _add_running(manager, "c1")
    manager._store.list_connections.return_value = [{"id": "c1", "enabled": True}]

    stopped = await manager.reconcile_once("fernet", "ws_default")

    assert stopped == []
    assert "c1" in manager.running_ids


async def test_reconcile_once_noop_when_nothing_running(manager: ChannelManager) -> None:
    """No pollers running -> never even queries the DB."""
    stopped = await manager.reconcile_once("fernet", "ws_default")

    assert stopped == []
    manager._store.list_connections.assert_not_awaited()


async def test_reconcile_loop_survives_transient_failure(manager: ChannelManager) -> None:
    """A transient DB error during reconciliation is logged, not raised."""
    _add_running(manager, "c1")
    manager._store.list_connections.side_effect = ConnectionRefusedError("db down")

    task = asyncio.create_task(manager.reconcile_loop("fernet", "ws_default", interval_seconds=0))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The failed reconcile must not have torn down the (still-healthy-looking) poller.
    assert "c1" in manager.running_ids
