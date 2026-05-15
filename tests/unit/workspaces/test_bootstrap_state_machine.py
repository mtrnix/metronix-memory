"""Unit tests for the ASOC workspace lifecycle state machine (MTRNIX-352, T2).

Pure transition matrix tests — no DB, no live services.
Tests focus on WorkspaceManager.bootstrap/archive/unarchive/delete + the
BootstrapStateEnum transition rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from metatron.core.exceptions import WorkspaceNotFoundError, WorkspaceStateTransitionError
from metatron.workspaces.bootstrap.models import BootstrapState, BootstrapStateEnum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    workspace_id: str = "ws-1",
    state: BootstrapStateEnum = BootstrapStateEnum.BOOTSTRAPPING,
    retry_count: int = 0,
    **kwargs: Any,
) -> BootstrapState:
    defaults: dict[str, Any] = dict(
        workspace_id=workspace_id,
        state=state,
        progress=0.0,
        current_step=None,
        last_processed_resource=None,
        last_processed_id=None,
        indexed_count=0,
        total_count=None,
        last_error=None,
        last_synced_at=None,
        retry_count=retry_count,
        next_retry_at=None,
        updated_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return BootstrapState(**defaults)


def _make_manager(bootstrap_store: AsyncMock, bootstrap_runner: AsyncMock) -> Any:
    from metatron.workspaces.manager import WorkspaceManager

    mgr = WorkspaceManager.__new__(WorkspaceManager)
    # Minimal attribute setup — bypass __init__
    from threading import Lock

    mgr._workspaces = {}
    mgr._active_workspace = {}
    mgr._lock = Lock()
    mgr._stats = {}
    mgr._persistence = None
    mgr._use_persistence = False
    mgr._bootstrap_store = bootstrap_store
    mgr._chat_persistence = None
    mgr._pg_store = None
    mgr._bootstrap_runner = bootstrap_runner
    mgr._async_lock = None
    return mgr


# ---------------------------------------------------------------------------
# bootstrap() state machine
# ---------------------------------------------------------------------------


class TestBootstrap:
    async def test_absent_creates_and_schedules(self) -> None:
        """absent → bootstrapping: creates PG row, calls schedule()."""
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = None  # absent
        new_state = _make_state(state=BootstrapStateEnum.BOOTSTRAPPING)
        store.upsert_initial.return_value = new_state

        mgr = _make_manager(store, runner)

        with patch.object(mgr, "_sync_workspace_to_postgres"):
            result = await mgr.bootstrap("ws-1", "asoc", {"url": "http://x"})

        assert result.state == BootstrapStateEnum.BOOTSTRAPPING
        store.upsert_initial.assert_called_once_with("ws-1")
        runner.schedule.assert_called_once()

    async def test_bootstrapping_is_idempotent(self) -> None:
        """bootstrapping → bootstrapping: returns existing state unchanged."""
        store = AsyncMock()
        runner = AsyncMock()
        existing = _make_state(state=BootstrapStateEnum.BOOTSTRAPPING)
        store.get.return_value = existing

        mgr = _make_manager(store, runner)
        result = await mgr.bootstrap("ws-1", "asoc", {})

        assert result is existing
        runner.schedule.assert_not_called()

    async def test_ready_is_idempotent(self) -> None:
        """ready → ready: idempotent."""
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.READY)

        mgr = _make_manager(store, runner)
        result = await mgr.bootstrap("ws-1", "asoc", {})

        assert result.state == BootstrapStateEnum.READY
        runner.schedule.assert_not_called()

    async def test_failed_resets_and_reschedules(self) -> None:
        """failed → bootstrapping: resets retry_count, re-launches job."""
        store = AsyncMock()
        runner = AsyncMock()
        failed_state = _make_state(state=BootstrapStateEnum.FAILED, retry_count=2)
        refreshed = _make_state(state=BootstrapStateEnum.BOOTSTRAPPING, retry_count=0)
        store.get.side_effect = [failed_state, refreshed]

        mgr = _make_manager(store, runner)
        result = await mgr.bootstrap("ws-1", "asoc", {})

        store.reset_retry.assert_called_once_with("ws-1")
        store.set_state.assert_called_once()
        runner.schedule.assert_called_once()
        assert result.state == BootstrapStateEnum.BOOTSTRAPPING

    async def test_archived_raises_409(self) -> None:
        """archived → bootstrap raises WorkspaceStateTransitionError."""
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.ARCHIVED)

        mgr = _make_manager(store, runner)

        with pytest.raises(WorkspaceStateTransitionError):
            await mgr.bootstrap("ws-1", "asoc", {})


# ---------------------------------------------------------------------------
# archive() state machine
# ---------------------------------------------------------------------------


class TestArchive:
    async def test_ready_transitions_to_archived(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.side_effect = [
            _make_state(state=BootstrapStateEnum.READY),
            _make_state(state=BootstrapStateEnum.ARCHIVED),
        ]
        mgr = _make_manager(store, runner)

        result = await mgr.archive("ws-1")

        store.set_state.assert_called_once()
        assert result.state == BootstrapStateEnum.ARCHIVED

    async def test_archived_is_idempotent(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.ARCHIVED)
        mgr = _make_manager(store, runner)

        result = await mgr.archive("ws-1")

        store.set_state.assert_not_called()
        assert result.state == BootstrapStateEnum.ARCHIVED

    async def test_bootstrapping_cannot_archive(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.BOOTSTRAPPING)
        mgr = _make_manager(store, runner)

        with pytest.raises(WorkspaceStateTransitionError):
            await mgr.archive("ws-1")

    async def test_not_found_raises_404(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = None
        mgr = _make_manager(store, runner)

        with pytest.raises(WorkspaceNotFoundError):
            await mgr.archive("ws-missing")


# ---------------------------------------------------------------------------
# unarchive() state machine
# ---------------------------------------------------------------------------


class TestUnarchive:
    async def test_archived_transitions_to_ready(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.side_effect = [
            _make_state(state=BootstrapStateEnum.ARCHIVED),
            _make_state(state=BootstrapStateEnum.READY),
        ]
        mgr = _make_manager(store, runner)

        result = await mgr.unarchive("ws-1")

        store.set_state.assert_called_once()
        assert result.state == BootstrapStateEnum.READY

    async def test_ready_cannot_unarchive(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.READY)
        mgr = _make_manager(store, runner)

        with pytest.raises(WorkspaceStateTransitionError):
            await mgr.unarchive("ws-1")

    async def test_not_found_raises_404(self) -> None:
        store = AsyncMock()
        runner = AsyncMock()
        store.get.return_value = None
        mgr = _make_manager(store, runner)

        with pytest.raises(WorkspaceNotFoundError):
            await mgr.unarchive("ws-missing")


# ---------------------------------------------------------------------------
# delete() — always succeeds, idempotent
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_calls_all_cleanup_steps(self) -> None:
        """delete() cancels task, deletes bootstrap row, and returns True."""
        store = AsyncMock()
        runner = AsyncMock()
        runner.cancel.return_value = True
        store.delete.return_value = True

        mgr = _make_manager(store, runner)
        # delete() wraps every step in contextlib.suppress(Exception), so
        # real-service errors (Qdrant, Neo4j) are silently ignored.  We only
        # need to verify that runner.cancel and store.delete were called.
        # Patch the two expensive async I/O calls to avoid real connections.
        with (
            patch("qdrant_client.AsyncQdrantClient", new=lambda **kw: AsyncMock()),
            patch("metatron.workspaces.manager.asyncio.to_thread", new=AsyncMock()),
        ):
            await mgr.delete("ws-1")

        runner.cancel.assert_called_once_with("ws-1")
        store.delete.assert_called_once_with("ws-1")

    async def test_delete_missing_workspace_is_idempotent(self) -> None:
        """delete() on absent workspace does not raise."""
        store = AsyncMock()
        runner = AsyncMock()
        runner.cancel.return_value = False
        store.delete.return_value = False  # nothing to delete

        mgr = _make_manager(store, runner)
        with (
            patch("qdrant_client.AsyncQdrantClient", new=lambda **kw: AsyncMock()),
            patch("metatron.workspaces.manager.asyncio.to_thread", new=AsyncMock()),
        ):
            # Should not raise regardless of return value
            await mgr.delete("ws-nonexistent")
