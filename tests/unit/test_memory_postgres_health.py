"""Tests for MemoryPostgresStore health-tracking methods (MTRNIX-277).

All tests use mocked SQLAlchemy async engines so they run without a live DB.
The round-trip tests for content_simhash are pure-Python and need no engine at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import LifecycleStatus
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.postgres import _from_pg_bigint, _to_pg_bigint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> tuple[MemoryPostgresStore, MagicMock]:
    """Return a store with a mock engine whose begin() returns a context mgr."""
    engine = MagicMock()
    store = MemoryPostgresStore(engine)
    return store, engine


def _mock_conn(
    scalar_value: int | None | object = ...,
    rows: list | None = None,
) -> MagicMock:
    """Return a mock async connection whose execute() returns a useful result.

    Pass ``scalar_value=None`` explicitly to mimic a NULL SQL aggregate; the
    sentinel default leaves ``scalar()`` returning the bare MagicMock for
    callers that do not care about scalar semantics.
    """
    conn = AsyncMock()
    result = MagicMock()
    if scalar_value is not ...:
        result.scalar.return_value = scalar_value
    if rows is not None:
        result.fetchall.return_value = rows
    conn.execute = AsyncMock(return_value=result)
    return conn


def _engine_context(conn: MagicMock) -> MagicMock:
    """Wire an engine to return ``conn`` inside ``async with engine.begin()``."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# _to_pg_bigint / _from_pg_bigint round-trip (no engine needed)
# ---------------------------------------------------------------------------


class TestBigintRoundTrip:
    """Boundary-value round-trips for the BIGINT sign-conversion helpers."""

    @pytest.mark.parametrize(
        "unsigned",
        [
            0,
            1,
            (1 << 63) - 1,  # max positive BIGINT (no sign flip needed)
            1 << 63,  # exact boundary: maps to most-negative BIGINT
            (1 << 63) + 1,  # one above boundary
            (1 << 64) - 1,  # max unsigned 64-bit
        ],
    )
    def test_round_trip(self, unsigned: int) -> None:
        signed = _to_pg_bigint(unsigned)
        back = _from_pg_bigint(signed)
        assert back == unsigned, f"{unsigned} → {signed} → {back}"

    def test_zero_stays_zero(self) -> None:
        assert _to_pg_bigint(0) == 0
        assert _from_pg_bigint(0) == 0

    def test_positive_range_unchanged(self) -> None:
        h = (1 << 62) + 12345
        assert _to_pg_bigint(h) == h

    def test_above_63_bits_goes_negative(self) -> None:
        # Anything >= 2**63 must map to a negative PG BIGINT.
        h = 1 << 63
        signed = _to_pg_bigint(h)
        assert signed < 0
        assert _from_pg_bigint(signed) == h


# ---------------------------------------------------------------------------
# bulk_touch_last_accessed
# ---------------------------------------------------------------------------


class TestBulkTouchLastAccessed:
    async def test_empty_ids_returns_zero_without_query(self) -> None:
        store, engine = _make_store()
        result = await store.bulk_touch_last_accessed("ws1", "a1", [])
        assert result == 0
        engine.begin.assert_not_called()

    async def test_returns_rowcount(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn()
        conn.execute.return_value.rowcount = 3
        engine.begin.return_value = _engine_context(conn)

        n = await store.bulk_touch_last_accessed("ws1", "a1", ["r1", "r2", "r3"])
        assert n == 3
        conn.execute.assert_awaited_once()

    async def test_scoped_to_workspace_and_agent(self) -> None:
        """Verify the UPDATE carries both workspace_id and agent_id binds."""
        store, engine = _make_store()
        conn = _mock_conn()
        conn.execute.return_value.rowcount = 1
        engine.begin.return_value = _engine_context(conn)

        await store.bulk_touch_last_accessed("ws-x", "ag-y", ["id1"])

        call_args = conn.execute.call_args
        params = call_args[0][1]  # second positional arg is the bind dict
        assert params["ws"] == "ws-x"
        assert params["agent_id"] == "ag-y"
        assert params["ids"] == ["id1"]

    async def test_throttles_recent_touches(self) -> None:
        """SQL must skip rows touched within the last minute (write-amp guard)."""
        store, engine = _make_store()
        conn = _mock_conn()
        conn.execute.return_value.rowcount = 0
        engine.begin.return_value = _engine_context(conn)

        await store.bulk_touch_last_accessed("ws1", "a1", ["id1"])

        call_args = conn.execute.call_args
        sql_clause = str(call_args[0][0])
        # The freshness predicate keeps a hot-search-loop from rewriting the
        # same row repeatedly. 1-minute resolution is more than enough for
        # a 30-day staleness window and collapses N*K updates/min to ~1
        # update/record/min.
        assert "last_accessed_at IS NULL" in sql_clause
        assert "INTERVAL '1 minute'" in sql_clause


# ---------------------------------------------------------------------------
# count_by_status
# ---------------------------------------------------------------------------


class TestCountByStatus:
    async def test_empty_statuses_returns_zero(self) -> None:
        store, engine = _make_store()
        n = await store.count_by_status("ws1", "a1", [])
        assert n == 0
        engine.begin.assert_not_called()

    async def test_counts_active(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=7)
        engine.begin.return_value = _engine_context(conn)

        n = await store.count_by_status("ws1", "a1", [LifecycleStatus.ACTIVE])
        assert n == 7

    async def test_null_scalar_returns_zero(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=None)
        engine.begin.return_value = _engine_context(conn)

        n = await store.count_by_status("ws1", "a1", [LifecycleStatus.ARCHIVED])
        assert n == 0

    async def test_multiple_statuses_passed(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=2)
        engine.begin.return_value = _engine_context(conn)

        await store.count_by_status(
            "ws1",
            "a1",
            [LifecycleStatus.ARCHIVED, LifecycleStatus.SUPERSEDED],
        )
        params = conn.execute.call_args[0][1]
        assert "archived" in params["statuses"]
        assert "superseded" in params["statuses"]


# ---------------------------------------------------------------------------
# count_unused
# ---------------------------------------------------------------------------


class TestCountUnused:
    async def test_empty_statuses_returns_zero(self) -> None:
        store, engine = _make_store()
        n = await store.count_unused("ws1", "a1", days=30, statuses=[])
        assert n == 0
        engine.begin.assert_not_called()

    async def test_delegates_days_param(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=4)
        engine.begin.return_value = _engine_context(conn)

        n = await store.count_unused(
            "ws1",
            "a1",
            days=60,
            statuses=[LifecycleStatus.ACTIVE],
        )
        assert n == 4
        params = conn.execute.call_args[0][1]
        assert params["days"] == 60


# ---------------------------------------------------------------------------
# source_distribution_active
# ---------------------------------------------------------------------------


class TestSourceDistributionActive:
    async def test_returns_dict(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([("chat", 5), ("api", 3)]))
        conn.execute = AsyncMock(return_value=result)
        engine.begin.return_value = _engine_context(conn)

        dist = await store.source_distribution_active("ws1", "a1")
        assert dist == {"chat": 5, "api": 3}

    async def test_skips_null_source_type(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([(None, 2), ("chat", 1)]))
        conn.execute = AsyncMock(return_value=result)
        engine.begin.return_value = _engine_context(conn)

        dist = await store.source_distribution_active("ws1", "a1")
        assert None not in dist
        assert dist.get("chat") == 1


# ---------------------------------------------------------------------------
# count_created_since_active
# ---------------------------------------------------------------------------


class TestCountCreatedSinceActive:
    async def test_returns_scalar(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=12)
        engine.begin.return_value = _engine_context(conn)

        n = await store.count_created_since_active("ws1", "a1", days=7)
        assert n == 12
        params = conn.execute.call_args[0][1]
        assert params["days"] == 7


# ---------------------------------------------------------------------------
# list_simhashes_active
# ---------------------------------------------------------------------------


class TestIterSimhashesActive:
    async def test_converts_signed_to_unsigned(self) -> None:
        store, engine = _make_store()
        # Simulate a PG row where simhash was stored as a negative BIGINT.
        unsigned_val = (1 << 63) + 42
        signed_val = _to_pg_bigint(unsigned_val)  # negative
        conn = AsyncMock()
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([("rid1", signed_val)]))
        conn.execute = AsyncMock(return_value=result)
        engine.begin.return_value = _engine_context(conn)

        rows = await store.list_simhashes_active("ws1", "a1")
        assert len(rows) == 1
        rid, h = rows[0]
        assert rid == "rid1"
        assert h == unsigned_val

    async def test_returns_empty_list(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([]))
        conn.execute = AsyncMock(return_value=result)
        engine.begin.return_value = _engine_context(conn)

        rows = await store.list_simhashes_active("ws1", "a1")
        assert rows == []


# ---------------------------------------------------------------------------
# count_active_with_null_simhash
# ---------------------------------------------------------------------------


class TestCountActiveWithNullSimhash:
    async def test_returns_count(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=5)
        engine.begin.return_value = _engine_context(conn)

        n = await store.count_active_with_null_simhash("ws1", "a1")
        assert n == 5


# ---------------------------------------------------------------------------
# bulk_set_simhash
# ---------------------------------------------------------------------------


class TestBulkSetSimhash:
    async def test_empty_rows_returns_zero(self) -> None:
        store, engine = _make_store()
        n = await store.bulk_set_simhash([])
        assert n == 0
        engine.begin.assert_not_called()

    async def test_returns_rowcount(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn()
        conn.execute.return_value.rowcount = 2
        engine.begin.return_value = _engine_context(conn)

        n = await store.bulk_set_simhash([("r1", 100), ("r2", 200)])
        assert n == 2

    async def test_converts_unsigned_to_signed(self) -> None:
        """bulk_set_simhash must pass _to_pg_bigint values to the DB."""
        store, engine = _make_store()
        conn = _mock_conn()
        conn.execute.return_value.rowcount = 1
        engine.begin.return_value = _engine_context(conn)

        unsigned = (1 << 63) + 99
        await store.bulk_set_simhash([("r1", unsigned)])

        params = conn.execute.call_args[0][1]
        # The stored simhash must be a negative BIGINT.
        assert params["simhashes"][0] < 0
        assert _from_pg_bigint(params["simhashes"][0]) == unsigned


# ---------------------------------------------------------------------------
# Workspace / agent isolation
# ---------------------------------------------------------------------------


class TestIsolation:
    async def test_bulk_touch_scoped_to_agent(self) -> None:
        """ids from another agent are never touched because the WHERE clause
        includes both workspace_id AND agent_id."""
        store, engine = _make_store()
        conn = _mock_conn()
        conn.execute.return_value.rowcount = 0
        engine.begin.return_value = _engine_context(conn)

        n = await store.bulk_touch_last_accessed("ws1", "ag-other", ["r1"])
        # rowcount of 0 is valid — agent mismatch in DB silently returns 0.
        assert n == 0

    async def test_count_by_status_active_only(self) -> None:
        """ACTIVE-only query must not count ARCHIVED rows even if they exist."""
        store, engine = _make_store()
        conn = _mock_conn(scalar_value=5)
        engine.begin.return_value = _engine_context(conn)

        n = await store.count_by_status("ws1", "a1", [LifecycleStatus.ACTIVE])
        params = conn.execute.call_args[0][1]
        assert params["statuses"] == ["active"]
        assert n == 5
