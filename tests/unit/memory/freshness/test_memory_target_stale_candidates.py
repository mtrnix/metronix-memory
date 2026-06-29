"""Unit tests for ``list_stale_candidates`` (MTRNIX-316).

* ``FreshnessTarget.list_stale_candidates`` — default Protocol behaviour
  is empty; both concrete adapters inherit it explicitly. KB returns ``[]``;
  memory delegates to the PG store.
* ``MemoryTarget.list_stale_candidates`` — thin pass-through.
* ``MemoryPostgresStore.list_stale_candidates`` — SQL shape covered via a
  mocked SQLAlchemy engine (no live PG).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from metronix.memory.freshness.target_memory import MemoryTarget


class TestMemoryTargetDelegation:
    async def test_delegates_to_pg_store(self) -> None:
        pg = AsyncMock()
        pg.list_stale_candidates.return_value = ["rec-1", "rec-2", "rec-3"]

        target = MemoryTarget(
            pg_store=pg,
            qdrant_store_factory=lambda _ws: MagicMock(),
        )
        older_than = datetime.now(UTC) - timedelta(days=30)

        out = await target.list_stale_candidates("ws-A", older_than=older_than, limit=10)

        assert out == ["rec-1", "rec-2", "rec-3"]
        pg.list_stale_candidates.assert_awaited_once_with("ws-A", older_than=older_than, limit=10)

    async def test_forwards_empty_list(self) -> None:
        pg = AsyncMock()
        pg.list_stale_candidates.return_value = []

        target = MemoryTarget(
            pg_store=pg,
            qdrant_store_factory=lambda _ws: MagicMock(),
        )
        out = await target.list_stale_candidates("ws-A", older_than=datetime.now(UTC), limit=500)

        assert out == []


class TestRawDocumentTargetDefault:
    async def test_raw_document_target_returns_empty(self) -> None:
        """KB adapter inherits the default empty list (MTRNIX-316 scope).

        KB-side scheduled scan is deferred to MTRNIX-316-follow.
        """
        from metronix.ingestion.freshness.target_raw_document import RawDocumentTarget

        pg = AsyncMock()
        target = RawDocumentTarget(
            pg_store=pg,
            qdrant_factory=lambda _ws: MagicMock(),
        )

        out = await target.list_stale_candidates("ws-A", older_than=datetime.now(UTC), limit=10)

        assert out == []
        # PG not touched — default implementation does not query.
        pg.get_raw_document_by_id.assert_not_called()


class TestMemoryPostgresStoreQueryShape:
    async def test_list_stale_candidates_query_and_params(self) -> None:
        """Assert the SQL query binds workspace_id, older_than, limit and
        filters out terminal statuses.
        """
        from metronix.storage.memory_postgres import MemoryPostgresStore

        engine = MagicMock()
        # Mock engine.begin() context manager.
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.execute.return_value = MagicMock(
            fetchall=lambda: [SimpleNamespace(_mapping={"id": "rec-1"})],
        )
        # conn.execute returns a mock whose .fetchall() is callable.
        fetch_result = MagicMock()
        fetch_result.fetchall.return_value = [("rec-1",), ("rec-2",)]
        conn.execute.return_value = fetch_result

        # Fake the async context manager `engine.begin()`.
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        engine.begin = MagicMock(return_value=cm)

        store = MemoryPostgresStore(engine)
        older_than = datetime(2026, 1, 1, tzinfo=UTC)

        out = await store.list_stale_candidates("ws-A", older_than=older_than, limit=42)

        assert out == ["rec-1", "rec-2"]
        # Verify the execute was called with expected bound parameters.
        call_args = conn.execute.await_args
        sql_text = str(call_args.args[0])
        params: dict[str, Any] = call_args.args[1]
        assert params == {
            "ws": "ws-A",
            "older_than": older_than,
            "limit": 42,
        }
        # Query filters out terminal statuses.
        assert "stale" in sql_text.lower()
        assert "superseded" in sql_text.lower()
        assert "archived" in sql_text.lower()
        # Orders by updated_at ASC so oldest stale candidates come first.
        assert "updated_at" in sql_text.lower()
        assert "asc" in sql_text.lower()
