"""Unit test for ChatPersistence.delete_threads_for_workspace (MTRNIX-352, T2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from metatron.chat.persistence import ChatPersistence


def _make_row(data: dict[str, Any]) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: data[k]
    mapping.get = lambda k, default=None: data.get(k, default)
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


def _make_persistence(rows: list[dict[str, Any]]) -> tuple[ChatPersistence, AsyncMock]:
    engine = MagicMock()
    conn = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [_make_row(r) for r in rows]
    conn.execute.return_value = result
    engine.begin.return_value = _FakeCtx(conn)
    return ChatPersistence(engine), conn


class TestDeleteThreadsForWorkspace:
    async def test_returns_count_of_deleted_threads(self) -> None:
        rows = [
            {"thread_id": "aaaa-0001"},
            {"thread_id": "bbbb-0002"},
        ]
        persistence, conn = _make_persistence(rows)
        count = await persistence.delete_threads_for_workspace("ws-1")

        assert count == 2

    async def test_uses_correct_workspace_id_param(self) -> None:
        persistence, conn = _make_persistence([])
        await persistence.delete_threads_for_workspace("ws-asoc-42")

        params = conn.execute.call_args.args[1]
        assert params["workspace_id"] == "ws-asoc-42"

    async def test_sql_targets_workspace_id_column(self) -> None:
        persistence, conn = _make_persistence([])
        await persistence.delete_threads_for_workspace("ws-1")

        sql_text = str(conn.execute.call_args.args[0])
        assert "workspace_id" in sql_text
        assert "DELETE" in sql_text.upper()

    async def test_zero_rows_returns_zero(self) -> None:
        persistence, conn = _make_persistence([])
        count = await persistence.delete_threads_for_workspace("ws-empty")
        assert count == 0
