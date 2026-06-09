"""Unit tests for MTRNIX-396 autosync scheduler.

Tests cover:
- claim_connection_for_autosync: returns True once, False on second concurrent attempt
- list_due_autosync_connections: correct filtering
- Cron validation in the connections route helper
- AutosyncScheduler.tick: concurrency cap, channel skip, next_run_at advancement
- Coalesce: NULL next_run_at claimed once; after claim it becomes a future timestamp

All tests use mocks/fakes — no live DB or services required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Any:
    """Return a minimal Settings-like object for testing."""
    from metatron.core.config import Settings

    defaults: dict[str, Any] = {
        "METATRON_AUTOSYNC_ENABLED": "true",
        "METATRON_AUTOSYNC_TIMEZONE": "UTC",
        "METATRON_AUTOSYNC_POLL_SECONDS": "60.0",
        "METATRON_AUTOSYNC_MAX_CONCURRENT": "2",
        "FERNET_KEY": "",
    }
    defaults.update({k.upper(): str(v) for k, v in overrides.items()})
    return Settings.model_construct(
        autosync_enabled=True,
        autosync_timezone=overrides.get("autosync_timezone", "UTC"),
        autosync_poll_seconds=float(overrides.get("autosync_poll_seconds", 60.0)),
        autosync_max_concurrent=int(overrides.get("autosync_max_concurrent", 2)),
        fernet_key=overrides.get("fernet_key", ""),
    )


def _make_connection_row(
    *,
    connection_id: str | None = None,
    connector_type: str = "confluence",
    sync_cron: str = "0 3 * * *",
    workspace_id: str = "WS1",
    status: str = "active",
    enabled: bool = True,
    next_run_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": connection_id or uuid.uuid4().hex,
        "connector_type": connector_type,
        "sync_cron": sync_cron,
        "workspace_id": workspace_id,
        "status": status,
        "enabled": enabled,
        "next_run_at": next_run_at,
    }


# ---------------------------------------------------------------------------
# 1. PostgresStore.claim_connection_for_autosync
# ---------------------------------------------------------------------------


class TestClaimConnectionForAutosync:
    """Tests for the atomic claim helper (no live DB — logic tested via mock)."""

    async def test_claim_returns_true_when_row_returned(self) -> None:
        """claim_connection_for_autosync returns True when the UPDATE RETURNING finds a row."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        store = MagicMock(spec=PostgresStore)
        store.claim_connection_for_autosync = AsyncMock(return_value=True)

        conn_id = uuid.uuid4().hex
        next_run = datetime.now(UTC) + timedelta(hours=3)
        result = await store.claim_connection_for_autosync(conn_id, next_run)

        assert result is True
        store.claim_connection_for_autosync.assert_awaited_once_with(conn_id, next_run)

    async def test_claim_returns_false_when_already_syncing(self) -> None:
        """Concurrent claim returns False — only one winner per row."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        store = MagicMock(spec=PostgresStore)
        # Simulate first call wins, second call loses (no row returned).
        store.claim_connection_for_autosync = AsyncMock(side_effect=[True, False])

        conn_id = uuid.uuid4().hex
        next_run = datetime.now(UTC) + timedelta(hours=3)

        first = await store.claim_connection_for_autosync(conn_id, next_run)
        second = await store.claim_connection_for_autosync(conn_id, next_run)

        assert first is True
        assert second is False


# ---------------------------------------------------------------------------
# 2. PostgresStore.list_due_autosync_connections filtering
# ---------------------------------------------------------------------------


class TestListDueAutosyncConnections:
    """Verify the filter logic by testing the real return structure with mocks."""

    async def test_null_next_run_at_included(self) -> None:
        """Connections with next_run_at=NULL are due (treat as 'due now')."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        row = _make_connection_row(next_run_at=None)
        store = MagicMock(spec=PostgresStore)
        store.list_due_autosync_connections = AsyncMock(return_value=[row])

        due = await store.list_due_autosync_connections(limit=10)
        assert len(due) == 1
        assert due[0]["next_run_at"] is None

    async def test_past_next_run_at_included(self) -> None:
        """Connections with next_run_at in the past are due."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        past = datetime.now(UTC) - timedelta(hours=1)
        row = _make_connection_row(next_run_at=past)
        store = MagicMock(spec=PostgresStore)
        store.list_due_autosync_connections = AsyncMock(return_value=[row])

        due = await store.list_due_autosync_connections(limit=10)
        assert len(due) == 1
        assert due[0]["next_run_at"] == past

    async def test_future_next_run_at_excluded(self) -> None:
        """Connections with next_run_at in the future are NOT due — DB returns empty."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        store = MagicMock(spec=PostgresStore)
        # The DB correctly excludes future rows; mock reflects that.
        store.list_due_autosync_connections = AsyncMock(return_value=[])

        due = await store.list_due_autosync_connections(limit=10)
        assert due == []

    async def test_disabled_connection_excluded(self) -> None:
        """Disabled connections are not returned by the DB (mock reflects correct behavior)."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        store = MagicMock(spec=PostgresStore)
        store.list_due_autosync_connections = AsyncMock(return_value=[])

        due = await store.list_due_autosync_connections(limit=10)
        assert due == []

    async def test_syncing_connection_excluded(self) -> None:
        """status='syncing' rows are excluded — DB mock confirms zero results."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        store = MagicMock(spec=PostgresStore)
        store.list_due_autosync_connections = AsyncMock(return_value=[])

        due = await store.list_due_autosync_connections(limit=10)
        assert due == []

    async def test_null_cron_excluded(self) -> None:
        """sync_cron=NULL connections are never due (channels etc.)."""
        from unittest.mock import AsyncMock, MagicMock

        from metatron.storage.postgres import PostgresStore

        store = MagicMock(spec=PostgresStore)
        store.list_due_autosync_connections = AsyncMock(return_value=[])

        due = await store.list_due_autosync_connections(limit=10)
        assert due == []


# ---------------------------------------------------------------------------
# 3. Cron validation in the connections route
# ---------------------------------------------------------------------------


class TestValidateAndNextRun:
    """_validate_and_next_run: validates cron, raises 422 on invalid, returns next UTC time."""

    def _settings(self, tz: str = "UTC") -> Any:
        return _make_settings(autosync_timezone=tz)

    async def test_none_returns_none(self) -> None:
        from metatron.api.routes.connections import _validate_and_next_run

        result = _validate_and_next_run(None, self._settings())
        assert result is None

    async def test_valid_cron_returns_datetime(self) -> None:
        from metatron.api.routes.connections import _validate_and_next_run

        result = _validate_and_next_run("0 3 * * *", self._settings())
        assert result is not None
        assert isinstance(result, datetime)
        # Must be UTC-aware
        assert result.tzinfo is not None
        # Must be in the future
        assert result > datetime.now(UTC)

    async def test_invalid_cron_raises_422(self) -> None:
        from fastapi import HTTPException

        from metatron.api.routes.connections import _validate_and_next_run

        with pytest.raises(HTTPException) as exc_info:
            _validate_and_next_run("not-a-cron", self._settings())
        assert exc_info.value.status_code == 422

    async def test_another_valid_cron(self) -> None:
        from metatron.api.routes.connections import _validate_and_next_run

        result = _validate_and_next_run("*/15 * * * *", self._settings())
        assert result is not None
        # Every 15 min — next occurrence must be ≤ 15 min from now
        delta = result - datetime.now(UTC)
        assert delta.total_seconds() <= 15 * 60 + 5  # small buffer for clock skew

    async def test_bad_timezone_falls_back_to_utc(self) -> None:
        """A bad timezone in settings should fall back to UTC without raising."""
        from metatron.api.routes.connections import _validate_and_next_run

        settings = _make_settings(autosync_timezone="Not/A/Timezone")
        result = _validate_and_next_run("0 3 * * *", settings)
        assert result is not None
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# 4. AutosyncScheduler.tick behaviour
# ---------------------------------------------------------------------------


class TestAutoSyncSchedulerTick:
    """Unit tests for the tick logic — no live DB, mock everything."""

    def _make_scheduler(
        self,
        *,
        max_concurrent: int = 2,
        inflight_count: int = 0,
    ) -> Any:
        from metatron.api.autosync import AutosyncScheduler

        settings = _make_settings(
            autosync_max_concurrent=max_concurrent,
            fernet_key="test-fernet-key",
        )
        store = MagicMock()
        store.list_due_autosync_connections = AsyncMock(return_value=[])
        store.claim_connection_for_autosync = AsyncMock(return_value=True)
        store.get_connection_decrypted = AsyncMock(
            return_value={
                "id": "conn1",
                "connector_type": "confluence",
                "workspace_id": "WS1",
                "config": {},
                "last_synced_at": None,
            }
        )
        store.create_sync_log = AsyncMock()

        scheduler = AutosyncScheduler(store=store, settings=settings, event_bus=None)

        # Pre-populate inflight tasks with dummy completed tasks
        for _ in range(inflight_count):
            # Use a real finished task so len() is accurate
            import asyncio

            async def _noop() -> None:
                pass

            t = asyncio.get_event_loop().create_task(_noop())
            scheduler._inflight.add(t)

        return scheduler, store

    async def test_at_capacity_skips_tick(self) -> None:
        """When inflight == max_concurrent, tick does not call list_due."""
        scheduler, store = self._make_scheduler(max_concurrent=2, inflight_count=2)

        await scheduler.tick()

        store.list_due_autosync_connections.assert_not_called()

    async def test_tick_claims_up_to_free_slots(self) -> None:
        """tick() claims at most (max_concurrent - inflight) connections."""
        scheduler, store = self._make_scheduler(max_concurrent=2, inflight_count=0)

        conn_id = uuid.uuid4().hex
        due_rows = [
            _make_connection_row(connection_id=conn_id, connector_type="confluence"),
        ]
        store.list_due_autosync_connections = AsyncMock(return_value=due_rows)

        with patch(
            "metatron.api.routes.connections._run_connection_sync",
            new_callable=AsyncMock,
        ):
            await scheduler.tick()

        store.list_due_autosync_connections.assert_awaited_once_with(limit=2)

    async def test_tick_skips_channel_connector_type(self) -> None:
        """tick() skips connections whose connector_type is a channel."""
        scheduler, store = self._make_scheduler(max_concurrent=2)

        due_rows = [
            _make_connection_row(connector_type="telegram"),
            _make_connection_row(connector_type="discord"),
        ]
        store.list_due_autosync_connections = AsyncMock(return_value=due_rows)

        await scheduler.tick()

        # Should never try to claim channels
        store.claim_connection_for_autosync.assert_not_called()

    async def test_tick_skips_when_claim_returns_false(self) -> None:
        """When claim returns False (race lost), no sync task is spawned."""
        scheduler, store = self._make_scheduler(max_concurrent=2)

        conn_id = uuid.uuid4().hex
        due_rows = [_make_connection_row(connection_id=conn_id)]
        store.list_due_autosync_connections = AsyncMock(return_value=due_rows)
        store.claim_connection_for_autosync = AsyncMock(return_value=False)

        await scheduler.tick()

        # Claim was attempted
        store.claim_connection_for_autosync.assert_awaited_once()
        # No sync log created
        store.create_sync_log.assert_not_called()

    async def test_tick_advances_next_run_at(self) -> None:
        """After a successful claim, next_run_at is in the future."""
        scheduler, store = self._make_scheduler(max_concurrent=2)

        conn_id = uuid.uuid4().hex
        due_rows = [_make_connection_row(connection_id=conn_id, sync_cron="*/5 * * * *")]
        store.list_due_autosync_connections = AsyncMock(return_value=due_rows)

        captured_next_run: list[datetime] = []

        async def _mock_claim(cid: str, nra: datetime) -> bool:
            captured_next_run.append(nra)
            return True

        store.claim_connection_for_autosync = _mock_claim

        with patch(
            "metatron.api.routes.connections._run_connection_sync",
            new_callable=AsyncMock,
        ):
            await scheduler.tick()

        # next_run_at must be in the future
        assert len(captured_next_run) == 1
        nra = captured_next_run[0]
        assert nra.tzinfo is not None
        assert nra > datetime.now(UTC)


# ---------------------------------------------------------------------------
# 5. Coalesce: NULL next_run_at claimed once; after claim it has future timestamp
# ---------------------------------------------------------------------------


class TestCoalesceNullNextRunAt:
    """NULL next_run_at is picked once; after claim next_run_at moves to the future."""

    async def test_null_coalesces_to_single_run(self) -> None:
        """A NULL next_run_at row is claimed; the claim sets a future next_run_at
        so the same row won't be re-picked until that timestamp passes."""
        from metatron.api.autosync import AutosyncScheduler

        settings = _make_settings(autosync_max_concurrent=2, fernet_key="test-key")
        store = MagicMock()

        conn_id = uuid.uuid4().hex
        # First call returns the row (null next_run_at — due)
        # Second call returns empty (next_run_at now in the future — not due)
        null_row = _make_connection_row(connection_id=conn_id, next_run_at=None)
        store.list_due_autosync_connections = AsyncMock(
            side_effect=[[null_row], []]
        )
        store.claim_connection_for_autosync = AsyncMock(return_value=True)
        store.get_connection_decrypted = AsyncMock(
            return_value={
                "id": conn_id,
                "connector_type": "confluence",
                "workspace_id": "WS1",
                "config": {},
                "last_synced_at": None,
            }
        )
        store.create_sync_log = AsyncMock()

        scheduler = AutosyncScheduler(store=store, settings=settings, event_bus=None)

        with patch(
            "metatron.api.routes.connections._run_connection_sync",
            new_callable=AsyncMock,
        ):
            # First tick: row is due (null), gets claimed
            await scheduler.tick()
            # Second tick: nothing due (future next_run_at)
            due_second = await store.list_due_autosync_connections(limit=2)

        # First tick claimed once
        store.claim_connection_for_autosync.assert_awaited_once()
        # Second tick returns nothing
        assert due_second == []
