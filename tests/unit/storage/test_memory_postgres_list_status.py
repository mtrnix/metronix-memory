"""Unit tests for MemoryPostgresStore status filter + get_many_statuses (MTRNIX-314).

Covers:
* ``list_records(status=...)`` pushes the filter into the PG WHERE clause.
* ``count_records(status=...)`` returns the filtered total.
* ``get_many_statuses`` returns a dict keyed by record id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metronix.core.models import LifecycleStatus
from metronix.storage.memory_postgres import MemoryPostgresStore

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


class TestListRecordsStatusFilter:
    async def test_status_filter_single_value(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [_mock_row(_BASE_ROW)]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.list_records("ws1", status=[LifecycleStatus.ACTIVE])

        assert len(out) == 1
        sql = str(conn.execute.call_args.args[0])
        assert "status = ANY(:status_list)" in sql
        params = conn.execute.call_args.args[1]
        assert params["status_list"] == ["active"]

    async def test_status_filter_multi_value(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records(
            "ws1",
            status=[LifecycleStatus.ACTIVE, LifecycleStatus.CANDIDATE],
        )

        params = conn.execute.call_args.args[1]
        assert params["status_list"] == ["active", "candidate"]

    async def test_status_none_omits_filter(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", status=None)

        sql = str(conn.execute.call_args.args[0])
        assert "status = ANY" not in sql
        params = conn.execute.call_args.args[1]
        assert "status_list" not in params


class TestCountRecordsStatusFilter:
    async def test_count_status_filter_adds_where(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 7
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        total = await store.count_records(
            "ws1", status=[LifecycleStatus.ACTIVE, LifecycleStatus.CANDIDATE]
        )

        assert total == 7
        sql = str(conn.execute.call_args.args[0])
        assert "status = ANY(:status_list)" in sql
        params = conn.execute.call_args.args[1]
        assert params["status_list"] == ["active", "candidate"]

    async def test_count_status_none_omits_filter(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 42
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        total = await store.count_records("ws1", status=None)

        assert total == 42
        sql = str(conn.execute.call_args.args[0])
        assert "status = ANY" not in sql


class TestGetManyStatuses:
    async def test_empty_ids_returns_empty_dict(self) -> None:
        store, _ = _make_store()

        out = await store.get_many_statuses("ws1", [])

        assert out == {}

    async def test_returns_id_to_status_map(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        row1 = MagicMock()
        row1.__getitem__ = lambda self, i: ["mem001", "active"][i]
        row2 = MagicMock()
        row2.__getitem__ = lambda self, i: ["mem002", "archived"][i]
        result = MagicMock()
        result.fetchall.return_value = [row1, row2]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.get_many_statuses("ws1", ["mem001", "mem002", "mem003"])

        assert out == {
            "mem001": LifecycleStatus.ACTIVE,
            "mem002": LifecycleStatus.ARCHIVED,
        }
        sql = str(conn.execute.call_args.args[0])
        assert "id = ANY(:ids)" in sql
        assert "workspace_id = :ws" in sql
        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["ids"] == ["mem001", "mem002", "mem003"]

    async def test_unknown_status_value_defaults_to_active(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, i: ["mem001", "bogus_value"][i]
        result = MagicMock()
        result.fetchall.return_value = [row]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.get_many_statuses("ws1", ["mem001"])

        assert out == {"mem001": LifecycleStatus.ACTIVE}
