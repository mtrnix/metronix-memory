"""Tests for metronix.mcp.pagination — cursor-based pagination."""

from __future__ import annotations

import pytest

from metronix.mcp.pagination import (
    CursorPager,
    decode_cursor,
    encode_cursor,
)


class TestEncodeDecode:
    def test_roundtrip(self) -> None:
        data = {"offset": 20, "query": "hello"}
        cursor = encode_cursor(data)
        assert isinstance(cursor, str)
        decoded = decode_cursor(cursor)
        assert decoded == data

    def test_decode_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-a-valid-cursor!!!")

    def test_empty_dict_roundtrip(self) -> None:
        cursor = encode_cursor({})
        assert decode_cursor(cursor) == {}


class TestCursorPager:
    def test_first_page(self) -> None:
        pager = CursorPager(limit=3)
        result = pager.paginate(list(range(10)))
        assert result.items == [0, 1, 2]
        assert result.has_more is True
        assert result.next_cursor is not None
        assert result.total == 10

    def test_second_page_via_cursor(self) -> None:
        pager = CursorPager(limit=3)
        first = pager.paginate(list(range(10)))
        second = pager.paginate(list(range(10)), cursor=first.next_cursor)
        assert second.items == [3, 4, 5]
        assert second.has_more is True

    def test_last_page(self) -> None:
        pager = CursorPager(limit=5)
        items = list(range(7))
        first = pager.paginate(items)
        second = pager.paginate(items, cursor=first.next_cursor)
        assert second.items == [5, 6]
        assert second.has_more is False
        assert second.next_cursor is None

    def test_exact_fit_no_more(self) -> None:
        pager = CursorPager(limit=5)
        result = pager.paginate(list(range(5)))
        assert result.has_more is False

    def test_empty_items(self) -> None:
        pager = CursorPager(limit=10)
        result = pager.paginate([])
        assert result.items == []
        assert result.has_more is False
        assert result.total == 0

    def test_invalid_cursor_resets_to_zero(self) -> None:
        pager = CursorPager(limit=3)
        result = pager.paginate(list(range(5)), cursor="garbage")
        assert result.items == [0, 1, 2]

    def test_limit_clamped_to_max(self) -> None:
        pager = CursorPager(limit=200, max_limit=50)
        assert pager.limit == 50

    def test_create_cursor(self) -> None:
        pager = CursorPager(limit=10)
        cursor = pager.create_cursor(query="test", page=2)
        data = decode_cursor(cursor)
        assert data["query"] == "test"
        assert data["page"] == 2

    def test_total_override(self) -> None:
        pager = CursorPager(limit=2)
        result = pager.paginate([1, 2, 3], total=99)
        assert result.total == 99
