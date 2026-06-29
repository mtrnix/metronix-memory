"""Tests for MemoryPostgresStore (WS1)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.core.models import MemoryRecord, MemoryScope, MemorySnapshot
from metronix.storage.memory_postgres import MemoryPostgresStore


def _make_store() -> tuple[MemoryPostgresStore, MagicMock]:
    """Create store with a mocked engine."""
    engine = MagicMock()
    store = MemoryPostgresStore(engine)
    return store, engine


def _sample_record(**overrides) -> MemoryRecord:
    defaults = {
        "id": "mem001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "source_type": "conversation",
        "content": "user prefers dark mode",
        "tags": ["preference"],
        "importance_score": 0.8,
        "content_hash": "abc123",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _sample_snapshot(**overrides) -> MemorySnapshot:
    defaults = {
        "id": "snap001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "label": "before refactor",
        "trigger": "manual",
        "record_count": 10,
        "content_hash": "snapabc",
        "size_bytes": 4096,
        "storage_path": "/snapshots/snap001.jsonl.gz",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemorySnapshot(**defaults)


# ---------------------------------------------------------------------------
# Helpers to set up async engine mock
# ---------------------------------------------------------------------------

_RECORD_ROW = {
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
    "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
}

_SNAPSHOT_ROW = {
    "id": "snap001",
    "workspace_id": "ws1",
    "agent_id": "agent1",
    "label": "before refactor",
    "trigger": "manual",
    "record_count": 10,
    "content_hash": "snapabc",
    "size_bytes": 4096,
    "storage_path": "/snapshots/snap001.jsonl.gz",
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
}


def _mock_row(row_data: dict) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: row_data[k]
    mapping.get = lambda k, default=None: row_data.get(k, default)
    row = MagicMock()
    row._mapping = mapping
    return row


class _FakeCtx:
    """Async context manager that yields a fixed connection mock."""

    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        pass


def _conn_with_row(engine: MagicMock, row_data: dict | None, rowcount: int = 1):
    """Set up engine.begin() context returning a conn mock.

    If row_data is None, .first() returns None and .fetchall() returns [].
    """
    conn = AsyncMock()

    result = MagicMock()
    result.rowcount = rowcount
    if row_data is not None:
        row = _mock_row(row_data)
        result.first.return_value = row
        result.fetchall.return_value = [row]
    else:
        result.first.return_value = None
        result.fetchall.return_value = []

    conn.execute.return_value = result
    engine.begin.return_value = _FakeCtx(conn)
    return conn


# ===========================================================================
# save
# ===========================================================================


class TestSave:
    async def test_inserts_record(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)
        record = _sample_record()

        result = await store.save(record)

        assert result.id == "mem001"
        conn.execute.assert_called_once()
        params = conn.execute.call_args.args[1]
        assert params["workspace_id"] == "ws1"
        assert params["content"] == "user prefers dark mode"

    async def test_sets_updated_at(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)
        record = _sample_record()
        before = datetime.now(UTC)

        await store.save(record)

        params = conn.execute.call_args.args[1]
        assert params["updated_at"] >= before

    async def test_serialises_tags_as_json(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)
        record = _sample_record(tags=["a", "b"])

        await store.save(record)

        params = conn.execute.call_args.args[1]
        assert params["tags"] == '["a", "b"]'

    async def test_serialises_metadata_as_json(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)
        record = _sample_record(metadata={"key": "val"})

        await store.save(record)

        params = conn.execute.call_args.args[1]
        assert params["metadata"] == '{"key": "val"}'


# ===========================================================================
# get
# ===========================================================================


class TestGet:
    async def test_returns_record_when_found(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, _RECORD_ROW)

        result = await store.get("ws1", "mem001")

        assert result is not None
        assert result.id == "mem001"
        assert result.scope == MemoryScope.PER_AGENT
        assert result.content == "user prefers dark mode"
        assert result.tags == ["preference"]

    async def test_returns_none_when_not_found(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None)

        result = await store.get("ws1", "missing")

        assert result is None


# ===========================================================================
# delete
# ===========================================================================


class TestDelete:
    async def test_returns_true_when_deleted(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None, rowcount=1)

        assert await store.delete("ws1", "mem001") is True

    async def test_returns_false_when_not_found(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None, rowcount=0)

        assert await store.delete("ws1", "nonexistent") is False


# ===========================================================================
# list
# ===========================================================================


class TestList:
    async def test_returns_records(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, _RECORD_ROW)

        records = await store.list_records("ws1")

        assert len(records) == 1
        assert records[0].id == "mem001"

    async def test_filters_by_agent_and_scope(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)

        await store.list_records("ws1", agent_id="agent1", scope=MemoryScope.GLOBAL)

        sql_text = str(conn.execute.call_args.args[0])
        assert "agent_id" in sql_text
        assert "scope" in sql_text

    async def test_empty_result(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None)

        records = await store.list_records("ws1")

        assert records == []

    async def test_pagination_params(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)

        await store.list_records("ws1", limit=10, offset=20)

        params = conn.execute.call_args.args[1]
        assert params["limit"] == 10
        assert params["offset"] == 20


# ===========================================================================
# reset
# ===========================================================================


class TestReset:
    async def test_returns_count_and_ids(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        row1 = MagicMock()
        row1.__getitem__ = lambda self, i: "id1"
        row2 = MagicMock()
        row2.__getitem__ = lambda self, i: "id2"
        result.fetchall.return_value = [row1, row2]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        count, ids = await store.reset("ws1", agent_id="agent1")

        assert count == 2
        assert ids == ["id1", "id2"]

    async def test_with_scope_filter(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        count, ids = await store.reset("ws1", scope=MemoryScope.SESSION)

        assert count == 0
        assert ids == []
        sql_text = str(conn.execute.call_args.args[0])
        assert "scope" in sql_text
        assert "RETURNING id" in sql_text


# ===========================================================================
# replace_for_agent (PROJ-272)
# ===========================================================================


class TestReplaceForAgent:
    async def test_atomic_delete_and_insert(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        delete_result = MagicMock()
        deleted_row = MagicMock()
        deleted_row.__getitem__ = lambda self, i: "id-old"
        delete_result.fetchall.return_value = [deleted_row]
        insert_result = MagicMock()
        conn.execute.side_effect = [delete_result, insert_result]
        engine.begin.return_value = _FakeCtx(conn)

        records = [_sample_record(id="id-new")]
        deleted_ids, inserted = await store.replace_for_agent("ws1", "agent1", records)

        assert deleted_ids == ["id-old"]
        assert inserted == 1
        # Two execute calls: DELETE, then INSERT.
        assert conn.execute.await_count == 2
        delete_sql = str(conn.execute.await_args_list[0].args[0])
        insert_sql = str(conn.execute.await_args_list[1].args[0])
        assert "DELETE FROM memory_records" in delete_sql
        assert "INSERT INTO memory_records" in insert_sql

    async def test_skips_insert_when_no_records(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        delete_result = MagicMock()
        delete_result.fetchall.return_value = []
        conn.execute.return_value = delete_result
        engine.begin.return_value = _FakeCtx(conn)

        deleted_ids, inserted = await store.replace_for_agent("ws1", "agent1", [])

        assert deleted_ids == []
        assert inserted == 0
        # Only the DELETE ran.
        assert conn.execute.await_count == 1

    async def test_rejects_workspace_or_agent_mismatch(self) -> None:
        store, _ = _make_store()
        bad = _sample_record(workspace_id="ws-other")
        with pytest.raises(ValueError, match="workspace/agent mismatch"):
            await store.replace_for_agent("ws1", "agent1", [bad])


# ===========================================================================
# get_by_hash
# ===========================================================================


class TestGetByHash:
    async def test_returns_record_when_hash_matches(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, _RECORD_ROW)

        result = await store.get_by_hash("ws1", "agent1", "abc123")

        assert result is not None
        assert result.id == "mem001"

    async def test_returns_none_when_no_match(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None)

        result = await store.get_by_hash("ws1", "agent1", "nonexistent")

        assert result is None


# ===========================================================================
# delete_expired
# ===========================================================================


class TestDeleteExpired:
    async def test_returns_count(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None, rowcount=3)

        count = await store.delete_expired("ws1")

        assert count == 3
        sql_text = str(conn.execute.call_args.args[0])
        assert "ttl_expires_at" in sql_text
        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws1"
        assert "now" in params


# ===========================================================================
# Snapshots
# ===========================================================================


class TestSaveSnapshot:
    async def test_inserts_snapshot(self) -> None:
        store, engine = _make_store()
        conn = _conn_with_row(engine, None)
        snap = _sample_snapshot()

        result = await store.save_snapshot(snap)

        assert result.id == "snap001"
        conn.execute.assert_called_once()
        params = conn.execute.call_args.args[1]
        assert params["id"] == "snap001"
        assert params["record_count"] == 10


class TestGetSnapshot:
    async def test_returns_snapshot_when_found(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, _SNAPSHOT_ROW)

        result = await store.get_snapshot("ws1", "snap001")

        assert result is not None
        assert result.id == "snap001"
        assert result.record_count == 10

    async def test_returns_none_when_not_found(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None)

        result = await store.get_snapshot("ws1", "missing")

        assert result is None


class TestDeleteSnapshot:
    async def test_returns_true_when_deleted(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None, rowcount=1)

        assert await store.delete_snapshot("ws1", "snap001") is True

    async def test_returns_false_when_not_found(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, None, rowcount=0)

        assert await store.delete_snapshot("ws1", "missing") is False


class TestListSnapshots:
    async def test_returns_snapshots_for_agent(self) -> None:
        store, engine = _make_store()
        _conn_with_row(engine, _SNAPSHOT_ROW)

        snapshots = await store.list_snapshots("ws1", "agent1")

        assert len(snapshots) == 1
        assert snapshots[0].id == "snap001"
