"""Unit tests for FreshnessStore review-queue extensions (MTRNIX-314).

Covers:
* ``list_review_entries`` with ``offset`` and ``reason`` filters.
* ``count_review_entries`` with the same WHERE construction.
* ``delete_review_entry`` happy path + idempotent re-delete + workspace isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.storage.freshness_pg import FreshnessStore


def _make_store() -> tuple[FreshnessStore, MagicMock]:
    engine = MagicMock()
    return FreshnessStore(engine), engine


def _mock_row(row_data: dict) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: row_data[k]
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


class TestListReviewEntriesExtensions:
    async def test_offset_pagination_passes_offset_param(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_review_entries("ws1", limit=10, offset=5)

        sql = str(conn.execute.call_args.args[0])
        assert "OFFSET :offset" in sql
        params = conn.execute.call_args.args[1]
        assert params["offset"] == 5
        assert params["limit"] == 10

    async def test_reason_filter_adds_where_clause(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_review_entries("ws1", reason="possible_duplicate")

        sql = str(conn.execute.call_args.args[0])
        assert "reason = :reason" in sql
        params = conn.execute.call_args.args[1]
        assert params["reason"] == "possible_duplicate"

    async def test_list_returns_entries_with_all_filters(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        row_data = {
            "id": "r1",
            "workspace_id": "ws1",
            "target_id": "m1",
            "target_kind": "memory_record",
            "reason": "possible_duplicate",
            "related_record_id": None,
            "content": "snippet",
            "confidence": 0.5,
            "created_at": datetime(2026, 4, 20, tzinfo=UTC),
        }
        result = MagicMock()
        result.fetchall.return_value = [_mock_row(row_data)]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        entries = await store.list_review_entries(
            "ws1",
            target_kind="memory_record",
            reason="possible_duplicate",
            record_id="m1",
            limit=5,
            offset=0,
        )

        assert len(entries) == 1
        assert entries[0].reason == "possible_duplicate"


class TestCountReviewEntries:
    async def test_count_returns_scalar(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 3
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        count = await store.count_review_entries(
            "ws1", target_kind="memory_record", reason="possible_duplicate"
        )

        assert count == 3
        sql = str(conn.execute.call_args.args[0])
        assert "SELECT COUNT" in sql.upper()
        assert "reason = :reason" in sql
        assert "target_kind = :target_kind" in sql
        params = conn.execute.call_args.args[1]
        assert params["reason"] == "possible_duplicate"
        assert params["target_kind"] == "memory_record"

    async def test_count_with_no_filters(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 10
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        count = await store.count_review_entries("ws1")

        assert count == 10


class TestDeleteReviewEntry:
    async def test_delete_returns_true_when_row_existed(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        deleted = await store.delete_review_entry("ws1", "r1")

        assert deleted is True
        sql = str(conn.execute.call_args.args[0])
        assert "DELETE FROM review_entries" in sql
        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["id"] == "r1"

    async def test_delete_returns_false_when_row_missing(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        deleted = await store.delete_review_entry("ws1", "r_missing")

        assert deleted is False

    async def test_delete_scopes_by_workspace(self) -> None:
        """Deleting with wrong workspace yields rowcount=0 even if id exists."""
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        deleted = await store.delete_review_entry("ws_other", "r1")

        assert deleted is False
        sql = str(conn.execute.call_args.args[0])
        # workspace_id must be in the WHERE clause to prevent cross-tenant deletes.
        assert "workspace_id = :ws" in sql
