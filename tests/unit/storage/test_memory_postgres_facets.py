"""Unit tests for MemoryPostgresStore.get_facets (MTRNIX-274).

The Memory Inspector filter dropdowns must only offer kind/source_type
values that actually exist in the workspace right now — not the full
static enum or values from a stale/filtered page.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metronix.core.models import MemoryKind
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


class TestGetFacets:
    async def test_returns_distinct_kinds_and_source_types(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        kind_result = MagicMock()
        kind_result.scalars.return_value.all.return_value = ["fact", "pinned"]
        source_type_result = MagicMock()
        source_type_result.scalars.return_value.all.return_value = ["confluence", "jira"]
        conn.execute.side_effect = [kind_result, source_type_result]
        engine.begin.return_value = _FakeCtx(conn)

        kinds, source_types = await store.get_facets("ws1")

        assert kinds == [MemoryKind.FACT, MemoryKind.PINNED]
        assert source_types == ["confluence", "jira"]

    async def test_scopes_to_workspace(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        conn.execute.side_effect = [empty_result, empty_result]
        engine.begin.return_value = _FakeCtx(conn)

        await store.get_facets("ws1")

        for call in conn.execute.call_args_list:
            params = call.args[1]
            assert params["ws"] == "ws1"

    async def test_excludes_blank_source_type(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        kind_result = MagicMock()
        kind_result.scalars.return_value.all.return_value = []
        source_type_result = MagicMock()
        source_type_result.scalars.return_value.all.return_value = ["confluence"]
        conn.execute.side_effect = [kind_result, source_type_result]
        engine.begin.return_value = _FakeCtx(conn)

        await store.get_facets("ws1")

        source_type_sql = str(conn.execute.call_args_list[1].args[0])
        assert "source_type != ''" in source_type_sql

    async def test_empty_workspace_returns_empty_lists(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        conn.execute.side_effect = [empty_result, empty_result]
        engine.begin.return_value = _FakeCtx(conn)

        kinds, source_types = await store.get_facets("ws1")

        assert kinds == []
        assert source_types == []
