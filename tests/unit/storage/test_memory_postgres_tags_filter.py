"""Unit tests for the MemoryPostgresStore tags push-down (#455).

Mirrors tests/unit/storage/test_memory_postgres_source_type_filter.py's
pattern for the existing status/kind/source_type filters.

Before this filter existed, ``metronix_memory_list`` applied ``tags`` in
Python over the already-paginated page and reported a tag-unfiltered
``total``, so a tag-filtered listing could not be paginated honestly.
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


def _wire(engine: MagicMock, *, scalar: int | None = None) -> AsyncMock:
    conn = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    result.scalar.return_value = scalar
    conn.execute.return_value = result
    engine.begin.return_value = _FakeCtx(conn)
    engine.connect.return_value = _FakeCtx(conn)
    return conn


class TestListRecordsTagsFilter:
    async def test_single_tag_pushes_overlap_clause(self) -> None:
        store, engine = _make_store()
        conn = _wire(engine)

        await store.list_records("ws1", tags=["decision"])

        sql = str(conn.execute.call_args.args[0])
        assert "tags ?| CAST(:tag_list AS text[])" in sql
        assert conn.execute.call_args.args[1]["tag_list"] == ["decision"]

    async def test_multiple_tags_are_passed_verbatim(self) -> None:
        store, engine = _make_store()
        conn = _wire(engine)

        await store.list_records("ws1", tags=["decision", "work"])

        assert conn.execute.call_args.args[1]["tag_list"] == ["decision", "work"]

    async def test_contains_all_operator_is_not_used(self) -> None:
        """``@>`` is "contains every tag" — the wrong semantics for this filter."""
        store, engine = _make_store()
        conn = _wire(engine)

        await store.list_records("ws1", tags=["decision", "work"])

        assert "tags @>" not in str(conn.execute.call_args.args[0])

    async def test_none_and_empty_add_no_clause(self) -> None:
        for value in (None, []):
            store, engine = _make_store()
            conn = _wire(engine)

            await store.list_records("ws1", tags=value)

            sql = str(conn.execute.call_args.args[0])
            assert "tag_list" not in sql
            assert "tag_list" not in conn.execute.call_args.args[1]


class TestCountRecordsTagsFilter:
    async def test_count_applies_the_same_clause(self) -> None:
        """A tag-filtered ``total`` is the whole point — count must match list."""
        store, engine = _make_store()
        conn = _wire(engine, scalar=5)

        out = await store.count_records("ws1", tags=["decision"])

        sql = str(conn.execute.call_args.args[0])
        assert "tags ?| CAST(:tag_list AS text[])" in sql
        assert conn.execute.call_args.args[1]["tag_list"] == ["decision"]
        assert out == 5

    async def test_count_none_adds_no_clause(self) -> None:
        store, engine = _make_store()
        conn = _wire(engine, scalar=15)

        await store.count_records("ws1", tags=None)

        assert "tag_list" not in str(conn.execute.call_args.args[0])
