"""Unit tests for MemoryPostgresStore.source_type_filter (MTRNIX-274).

Mirrors tests/unit/storage/test_memory_postgres_list_status.py's pattern for
the existing status/kind filters.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metronix.storage.memory_postgres import MemoryPostgresStore


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


class TestListRecordsSourceTypeFilter:
    async def test_source_type_filter_single_value(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", source_type_filter=["confluence"])

        sql = str(conn.execute.call_args.args[0])
        assert "source_type = ANY(:source_type_list)" in sql
        params = conn.execute.call_args.args[1]
        assert params["source_type_list"] == ["confluence"]

    async def test_source_type_filter_multi_value(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", source_type_filter=["confluence", "jira"])

        params = conn.execute.call_args.args[1]
        assert params["source_type_list"] == ["confluence", "jira"]

    async def test_source_type_none_omits_filter(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.list_records("ws1", source_type_filter=None)

        sql = str(conn.execute.call_args.args[0])
        assert "source_type = ANY" not in sql
        params = conn.execute.call_args.args[1]
        assert "source_type_list" not in params


class TestCountRecordsSourceTypeFilter:
    async def test_count_source_type_filter_adds_where(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 3
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        total = await store.count_records("ws1", source_type_filter=["jira"])

        assert total == 3
        sql = str(conn.execute.call_args.args[0])
        assert "source_type = ANY(:source_type_list)" in sql

    async def test_count_source_type_none_omits_filter(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 9
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        total = await store.count_records("ws1", source_type_filter=None)

        assert total == 9
        sql = str(conn.execute.call_args.args[0])
        assert "source_type = ANY" not in sql
