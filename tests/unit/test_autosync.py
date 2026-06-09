"""Tests for MTRNIX-396 autosync scheduler.

Two tiers:

- **Scheduler logic** (`TestComputeNextRun`, `TestValidateCron`,
  `TestAutoSyncSchedulerTick`, `TestCoalesceNullNextRunAt`) — pure logic /
  mocked store, no live services.
- **Live-PG integration** (`TestClaimConnectionForAutosyncLive`,
  `TestListDueAutosyncConnectionsLive`) — exercise the real SQL against a live
  PostgreSQL, same tier/style as ``test_postgres_sync_logs.py`` (which also
  lives in ``tests/unit/`` and hits a live PG via ``get_engine``/``get_session``).
  These are collected by ``make test``/``make test-all``; they require a
  reachable PG with migration 025 applied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from metatron.core.config import Settings
from metatron.storage.pg_connection import get_engine
from metatron.storage.postgres import PostgresStore

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Any:
    """Return a minimal Settings-like object for testing."""
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
# 1. compute_next_run helper (shared, autosync.py)
# ---------------------------------------------------------------------------


class TestComputeNextRun:
    """compute_next_run: tz-aware UTC next occurrence; bad tz → UTC fallback."""

    async def test_valid_cron_returns_future_utc(self) -> None:
        from metatron.api.autosync import compute_next_run

        result = compute_next_run("0 3 * * *", timezone="UTC")
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)  # normalized to UTC
        assert result > datetime.now(UTC)

    async def test_interval_cron_within_window(self) -> None:
        from metatron.api.autosync import compute_next_run

        result = compute_next_run("*/15 * * * *", timezone="UTC")
        delta = result - datetime.now(UTC)
        assert delta.total_seconds() <= 15 * 60 + 5

    async def test_bad_timezone_falls_back_to_utc(self) -> None:
        from metatron.api.autosync import compute_next_run

        result = compute_next_run("0 3 * * *", timezone="Not/A/Timezone")
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    async def test_non_utc_timezone_normalized_to_utc(self) -> None:
        """A non-UTC tz still yields a tz-aware UTC datetime in the future."""
        from metatron.api.autosync import compute_next_run

        result = compute_next_run("0 3 * * *", timezone="America/New_York")
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)
        assert result > datetime.now(UTC)


# ---------------------------------------------------------------------------
# 2. Cron validation in the connections route
# ---------------------------------------------------------------------------


class TestValidateCron:
    """_validate_cron: raises 422 on invalid cron, passes silently on valid."""

    async def test_valid_cron_passes(self) -> None:
        from metatron.api.routes.connections import _validate_cron

        # Should not raise
        _validate_cron("0 3 * * *")
        _validate_cron("*/15 * * * *")

    async def test_invalid_cron_raises_422(self) -> None:
        from fastapi import HTTPException

        from metatron.api.routes.connections import _validate_cron

        with pytest.raises(HTTPException) as exc_info:
            _validate_cron("not-a-cron")
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# 3. AutosyncScheduler.tick behaviour (mocked store)
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
# 4. Coalesce: NULL next_run_at claimed once; after claim it has future timestamp
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
        store.list_due_autosync_connections = AsyncMock(side_effect=[[null_row], []])
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


# ===========================================================================
# Live-PG integration tier (real SQL). Requires a reachable PostgreSQL with
# migration 025 applied. Same tier/style as test_postgres_sync_logs.py.
# ===========================================================================


@pytest.fixture
async def store() -> Any:
    s = Settings()
    yield PostgresStore(s.postgres_dsn)


@pytest.fixture
def ws_id() -> Any:
    """Create an isolated workspace row; yield its id."""
    wid = f"ws_as_{uuid.uuid4().hex[:10]}"
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": wid, "name": "t", "slug": wid},
        )
        conn.commit()
    yield wid


def _insert_connection(
    *,
    ws: str,
    connector_type: str = "jira",
    status: str = "active",
    enabled: bool = True,
    sync_cron: str | None = "0 3 * * *",
    next_run_at: datetime | None = None,
) -> str:
    """Insert a connection row directly via SQL and return its id."""
    cid = f"conn_as_{uuid.uuid4().hex[:10]}"
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO connections"
                " (id, workspace_id, connector_type, name, config_encrypted,"
                "  status, enabled, sync_cron, next_run_at)"
                " VALUES (:id, :ws, :ct, 'T', :cfg, :status, :enabled,"
                "         :sync_cron, :next_run_at)"
            ),
            {
                "id": cid,
                "ws": ws,
                "ct": connector_type,
                "cfg": b"x",
                "status": status,
                "enabled": enabled,
                "sync_cron": sync_cron,
                "next_run_at": next_run_at,
            },
        )
        conn.commit()
    return cid


class TestClaimConnectionForAutosyncLive:
    """Live-PG: the atomic claim guard (status != 'syncing')."""

    async def test_claim_true_then_false_on_second_call(self, store: Any, ws_id: str) -> None:
        """First claim wins (True); an immediate second claim loses (False)
        because the row is now status='syncing'."""
        cid = _insert_connection(ws=ws_id, status="active", next_run_at=None)
        next_run = datetime.now(UTC) + timedelta(hours=3)

        first = await store.claim_connection_for_autosync(cid, next_run)
        second = await store.claim_connection_for_autosync(cid, next_run)

        assert first is True
        assert second is False

    async def test_claim_false_when_disabled(self, store: Any, ws_id: str) -> None:
        """A disabled connection cannot be claimed."""
        cid = _insert_connection(ws=ws_id, enabled=False, next_run_at=None)
        next_run = datetime.now(UTC) + timedelta(hours=3)
        assert await store.claim_connection_for_autosync(cid, next_run) is False

    async def test_claim_false_when_future_next_run(self, store: Any, ws_id: str) -> None:
        """A connection whose next_run_at is in the future is not yet due."""
        future = datetime.now(UTC) + timedelta(hours=5)
        cid = _insert_connection(ws=ws_id, next_run_at=future)
        next_run = datetime.now(UTC) + timedelta(hours=3)
        assert await store.claim_connection_for_autosync(cid, next_run) is False

    async def test_claim_true_when_past_next_run(self, store: Any, ws_id: str) -> None:
        """A connection whose next_run_at is in the past is due."""
        past = datetime.now(UTC) - timedelta(hours=1)
        cid = _insert_connection(ws=ws_id, next_run_at=past)
        next_run = datetime.now(UTC) + timedelta(hours=3)
        assert await store.claim_connection_for_autosync(cid, next_run) is True


class TestListDueAutosyncConnectionsLive:
    """Live-PG: due-query filter branches against real SQL."""

    async def test_includes_null_and_past_excludes_future(
        self, store: Any, ws_id: str
    ) -> None:
        # The due-query is global (across all workspaces) by design and the test
        # DB may carry many leftover due rows, so a global LIMIT could truncate
        # our rows. Filter the result to this test's workspace before asserting.
        past = datetime.now(UTC) - timedelta(hours=1)
        future = datetime.now(UTC) + timedelta(hours=5)
        null_cid = _insert_connection(ws=ws_id, next_run_at=None)
        past_cid = _insert_connection(ws=ws_id, next_run_at=past)
        future_cid = _insert_connection(ws=ws_id, next_run_at=future)  # excluded

        due = await store.list_due_autosync_connections(limit=10000)
        my_ids = {row["id"] for row in due if row["workspace_id"] == ws_id}

        assert null_cid in my_ids
        assert past_cid in my_ids
        assert future_cid not in my_ids

    async def test_excludes_disabled(self, store: Any, ws_id: str) -> None:
        disabled_cid = _insert_connection(ws=ws_id, enabled=False, next_run_at=None)
        due = await store.list_due_autosync_connections(limit=10000)
        assert disabled_cid not in {row["id"] for row in due}

    async def test_excludes_null_cron(self, store: Any, ws_id: str) -> None:
        null_cron_cid = _insert_connection(ws=ws_id, sync_cron=None, next_run_at=None)
        due = await store.list_due_autosync_connections(limit=10000)
        assert null_cron_cid not in {row["id"] for row in due}

    async def test_excludes_syncing(self, store: Any, ws_id: str) -> None:
        syncing_cid = _insert_connection(ws=ws_id, status="syncing", next_run_at=None)
        due = await store.list_due_autosync_connections(limit=10000)
        assert syncing_cid not in {row["id"] for row in due}

    async def test_returns_lightweight_dict_shape(self, store: Any, ws_id: str) -> None:
        cid = _insert_connection(ws=ws_id, connector_type="jira", next_run_at=None)
        due = await store.list_due_autosync_connections(limit=10000)
        row = next(r for r in due if r["id"] == cid)
        assert set(row.keys()) == {"id", "connector_type", "sync_cron", "workspace_id"}
        assert row["connector_type"] == "jira"
        assert row["workspace_id"] == ws_id
        assert row["sync_cron"] == "0 3 * * *"
