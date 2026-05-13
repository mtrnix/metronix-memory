"""Unit tests for MemoryPostgresStore lifetime filter + session GC delete (Phase 2).

Covers:
* PG1 — list_records(lifetime="persistent") adds ttl_expires_at IS NULL clause
* PG2 — list_records(lifetime="session") adds ttl_expires_at IS NOT NULL AND > now()
* PG3 — list_records(lifetime="all") adds no filter
* PG4 — count_records(lifetime="session") mirrors list_records filter
* PG5 — delete_session_records_past_grace deletes only rows with ttl < cutoff
* PG6 — delete_session_records_past_grace is workspace-scoped
* PG7 — delete_session_records_past_grace respects limit
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.storage.memory_postgres import MemoryPostgresStore

# ---------------------------------------------------------------------------
# Helpers — mirrors test_memory_postgres_list_status.py patterns
# ---------------------------------------------------------------------------

_BASE_ROW = {
    "id": "mem001",
    "workspace_id": "ws1",
    "agent_id": "agent1",
    "scope": "per_agent",
    "source_type": "conversation",
    "content": "user prefers dark mode",
    "tags": ["preference"],
    "importance_score": 0.8,
    "ttl_expires_at": None,
    "content_hash": "abc123",
    "session_id": None,
    "metadata": {},
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    "status": "active",
    "freshness_score": 0.5,
    "superseded_by": None,
    "valid_from": None,
    "valid_until": None,
    "evidence_count": 0,
    "verification_state": None,
}


def _mock_row(row_data: dict) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: row_data[k]
    mapping.get = lambda k, default=None: row_data.get(k, default)
    row = MagicMock()
    row._mapping = mapping
    return row


class _FakeCtx:
    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        pass


def _make_store() -> tuple[MemoryPostgresStore, MagicMock]:
    engine = MagicMock()
    return MemoryPostgresStore(engine), engine


def _fake_conn(fetchall_return=None, scalar_return=None):  # type: ignore[no-untyped-def]
    conn = AsyncMock()
    result = MagicMock()
    if fetchall_return is not None:
        result.fetchall.return_value = fetchall_return
    if scalar_return is not None:
        result.scalar.return_value = scalar_return
    conn.execute.return_value = result
    return conn


# ---------------------------------------------------------------------------
# PG1 — lifetime=persistent
# ---------------------------------------------------------------------------


class TestListRecordsLifetimePersistent:
    async def test_pg1_persistent_adds_is_null_clause(self) -> None:
        store, engine = _make_store()
        conn = _fake_conn(fetchall_return=[])
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", lifetime="persistent")

        sql = str(conn.execute.call_args.args[0])
        assert "ttl_expires_at IS NULL" in sql

    async def test_pg1_persistent_excludes_session_rows(self) -> None:
        """Row WITH ttl_expires_at returns from query iff lifetime != persistent."""
        store, engine = _make_store()
        # Simulate that PG returned one row (persistent row, ttl IS NULL)
        row_data = {**_BASE_ROW, "ttl_expires_at": None}
        conn = _fake_conn(fetchall_return=[_mock_row(row_data)])
        engine.begin.return_value = _FakeCtx(conn)

        rows = await store.list_records("ws1", lifetime="persistent")
        assert len(rows) == 1
        assert rows[0].ttl_expires_at is None


# ---------------------------------------------------------------------------
# PG2 — lifetime=session
# ---------------------------------------------------------------------------


class TestListRecordsLifetimeSession:
    async def test_pg2_session_adds_is_not_null_clause(self) -> None:
        store, engine = _make_store()
        conn = _fake_conn(fetchall_return=[])
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", lifetime="session")

        sql = str(conn.execute.call_args.args[0])
        assert "ttl_expires_at IS NOT NULL" in sql
        assert "ttl_expires_at > now()" in sql

    async def test_pg2_session_row_returned_when_sql_matches(self) -> None:
        store, engine = _make_store()
        future_ttl = datetime(2099, 1, 1, tzinfo=UTC)
        row_data = {**_BASE_ROW, "ttl_expires_at": future_ttl, "session_id": "sess-1"}
        conn = _fake_conn(fetchall_return=[_mock_row(row_data)])
        engine.begin.return_value = _FakeCtx(conn)

        rows = await store.list_records("ws1", lifetime="session")
        assert len(rows) == 1
        assert rows[0].session_id == "sess-1"
        assert rows[0].ttl_expires_at is not None


# ---------------------------------------------------------------------------
# PG3 — lifetime=all
# ---------------------------------------------------------------------------


class TestListRecordsLifetimeAll:
    async def test_pg3_all_adds_no_ttl_where_clause(self) -> None:
        """lifetime='all' must NOT add a WHERE condition on ttl_expires_at.

        The column still appears in the SELECT list (_RECORD_COLUMNS), so we
        verify that neither the IS NULL nor the IS NOT NULL filter appears in
        the WHERE clause — not that the column itself is absent from SQL.
        """
        store, engine = _make_store()
        conn = _fake_conn(fetchall_return=[])
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", lifetime="all")

        sql = str(conn.execute.call_args.args[0])
        # WHERE clause must not contain either lifetime filter.
        # Split on WHERE to get only the clause portion.
        where_part = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
        assert "ttl_expires_at IS NULL" not in where_part
        assert "ttl_expires_at IS NOT NULL" not in where_part


# ---------------------------------------------------------------------------
# PG4 — count_records(lifetime=session) mirrors filter
# ---------------------------------------------------------------------------


class TestCountRecordsLifetime:
    async def test_pg4_session_lifetime_in_count_sql(self) -> None:
        store, engine = _make_store()
        conn = _fake_conn(scalar_return=3)
        engine.begin.return_value = _FakeCtx(conn)

        total = await store.count_records("ws1", lifetime="session")

        assert total == 3
        sql = str(conn.execute.call_args.args[0])
        assert "ttl_expires_at IS NOT NULL" in sql

    async def test_pg4_persistent_lifetime_in_count_sql(self) -> None:
        store, engine = _make_store()
        conn = _fake_conn(scalar_return=10)
        engine.begin.return_value = _FakeCtx(conn)

        await store.count_records("ws1", lifetime="persistent")

        sql = str(conn.execute.call_args.args[0])
        assert "ttl_expires_at IS NULL" in sql


# ---------------------------------------------------------------------------
# PG5/6/7 — delete_session_records_past_grace
# ---------------------------------------------------------------------------


class TestDeleteSessionRecordsPastGrace:
    async def test_pg5_returns_count_of_deleted_ids(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        # Simulate 2 rows deleted
        result.fetchall.return_value = [MagicMock(), MagicMock()]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        cutoff = datetime(2026, 4, 1, tzinfo=UTC)
        count = await store.delete_session_records_past_grace("ws1", grace_cutoff=cutoff)

        assert count == 2

    async def test_pg5_sql_uses_subquery_with_cutoff(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        cutoff = datetime(2026, 4, 1, tzinfo=UTC)
        await store.delete_session_records_past_grace("ws1", grace_cutoff=cutoff)

        sql = str(conn.execute.call_args.args[0])
        params = conn.execute.call_args.args[1]
        assert "DELETE FROM memory_records" in sql
        assert "ttl_expires_at IS NOT NULL" in sql
        assert "ttl_expires_at < :cutoff" in sql
        assert params["ws"] == "ws1"
        assert params["cutoff"] == cutoff

    async def test_pg6_workspace_scoped_param(self) -> None:
        """The DELETE subquery uses :ws for workspace isolation."""
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        cutoff = datetime(2026, 4, 1, tzinfo=UTC)
        await store.delete_session_records_past_grace("ws-only-this", grace_cutoff=cutoff)

        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws-only-this"

    async def test_pg7_limit_passed_to_query(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        cutoff = datetime(2026, 4, 1, tzinfo=UTC)
        await store.delete_session_records_past_grace("ws1", grace_cutoff=cutoff, limit=2)

        params = conn.execute.call_args.args[1]
        assert params["limit"] == 2

    async def test_pg5_persistent_rows_not_included_in_sql(self) -> None:
        """The SQL must filter ttl_expires_at IS NOT NULL, excluding persistent rows."""
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        cutoff = datetime(2026, 4, 1, tzinfo=UTC)
        await store.delete_session_records_past_grace("ws1", grace_cutoff=cutoff)

        sql = str(conn.execute.call_args.args[0])
        # Persistent rows (ttl IS NULL) must be excluded by the IS NOT NULL guard.
        assert "ttl_expires_at IS NOT NULL" in sql
