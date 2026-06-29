"""Unit tests for MCP memory utility helpers (PROJ-314)."""

from __future__ import annotations

import pytest

from metronix.core.models import LifecycleStatus
from metronix.mcp.tools._memory_utils import parse_status_filter


class TestParseStatusFilter:
    def test_none_returns_default_active(self) -> None:
        out = parse_status_filter(None)
        assert out == [LifecycleStatus.ACTIVE]

    def test_all_sentinel_disables_filter(self) -> None:
        assert parse_status_filter(["all"]) is None

    def test_valid_multi_value(self) -> None:
        out = parse_status_filter(["active", "candidate"])
        assert out == [LifecycleStatus.ACTIVE, LifecycleStatus.CANDIDATE]

    def test_invalid_raises_with_hint(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            parse_status_filter(["bogus"])
        # Hint should list valid values incl. 'all'.
        try:
            parse_status_filter(["nope"])
        except ValueError as exc:
            assert "all" in str(exc)
            assert "active" in str(exc)

    def test_empty_list_returns_empty_list(self) -> None:
        """An empty list is not the same as None — it simply parses zero items."""
        out = parse_status_filter([])
        assert out == []
