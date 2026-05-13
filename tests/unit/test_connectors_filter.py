"""Tests for the shared sub-minute cursor post-filter (MTRNIX-332)."""

from __future__ import annotations

from datetime import UTC, datetime

from metatron.connectors._filter import is_strictly_after, parse_iso_timestamp


class TestParseIsoTimestamp:
    def test_parses_with_z_suffix(self) -> None:
        ts = parse_iso_timestamp("2026-05-12T11:02:26.000Z")
        assert ts == datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)

    def test_parses_with_numeric_offset(self) -> None:
        ts = parse_iso_timestamp("2026-05-12T14:02:26.002+0300")
        # The parsed value preserves the +0300 offset; the same instant
        # in UTC is 11:02:26.
        assert ts is not None
        assert ts.utcoffset() is not None
        assert ts.astimezone(UTC) == datetime(2026, 5, 12, 11, 2, 26, 2000, tzinfo=UTC)

    def test_none_returns_none(self) -> None:
        assert parse_iso_timestamp(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_iso_timestamp("") is None

    def test_non_string_returns_none(self) -> None:
        assert parse_iso_timestamp(42) is None
        assert parse_iso_timestamp({"weird": "shape"}) is None

    def test_unparseable_returns_none(self) -> None:
        assert parse_iso_timestamp("not-a-date") is None


class TestIsStrictlyAfter:
    def test_since_none_always_keeps(self) -> None:
        """Initial sync (since=None) must not drop anything."""
        assert is_strictly_after("2026-05-12T11:02:26.000Z", None) is True
        assert is_strictly_after(None, None) is True

    def test_strictly_after_keeps(self) -> None:
        since = datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)
        assert is_strictly_after("2026-05-12T11:02:27.000Z", since) is True

    def test_equal_drops(self) -> None:
        """Boundary equality: same instant as cursor must be filtered out."""
        since = datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)
        assert is_strictly_after("2026-05-12T11:02:26.000Z", since) is False

    def test_strictly_before_drops(self) -> None:
        since = datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)
        assert is_strictly_after("2026-05-12T11:02:25.000Z", since) is False

    def test_missing_timestamp_keeps_with_cursor(self) -> None:
        """When the source doesn't include an `updated`, over-fetch rather
        than silently drop the doc."""
        since = datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)
        assert is_strictly_after(None, since) is True
        assert is_strictly_after("", since) is True

    def test_unparseable_timestamp_keeps(self) -> None:
        """Same safety bias: parse failure → over-fetch."""
        since = datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)
        assert is_strictly_after("garbage", since) is True

    def test_tz_aware_comparison_across_offsets(self) -> None:
        """Comparing UTC cursor against +03:00 timestamp — same instant."""
        since = datetime(2026, 5, 12, 11, 2, 26, tzinfo=UTC)
        # 14:02:26 +0300 == 11:02:26 UTC → equal → drop.
        assert is_strictly_after("2026-05-12T14:02:26.000+0300", since) is False
        # 14:02:27 +0300 == 11:02:27 UTC → after → keep.
        assert is_strictly_after("2026-05-12T14:02:27.000+0300", since) is True
