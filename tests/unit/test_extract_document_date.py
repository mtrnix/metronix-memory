"""Tests for extract_document_date() smart date extraction."""

from __future__ import annotations

from datetime import datetime

from metatron.ingestion.pipeline import extract_document_date


class TestTitleDateExtraction:
    def test_date_from_title_iso(self) -> None:
        """Title has ISO date — use it."""
        result = extract_document_date("2026-01-27 Summary", "some content")
        assert result == "2026-01-27"

    def test_date_from_title_european(self) -> None:
        """Title has European date."""
        result = extract_document_date("Встреча 03.02.2026", "some content")
        assert result == "2026-02-03"

    def test_date_from_title_russian_month(self) -> None:
        """Title has Russian date without year — infer from updated_at."""
        result = extract_document_date(
            "27 января Summary",
            "some content",
            updated_at=datetime(2026, 2, 2),
        )
        assert result == "2026-01-27"

    def test_date_from_title_english_month(self) -> None:
        """Title has English date."""
        result = extract_document_date(
            "January 15 meeting notes",
            "some content",
            updated_at=datetime(2026, 1, 20),
        )
        assert result == "2026-01-15"


class TestContentDateExtraction:
    def test_date_from_content_when_title_has_none(self) -> None:
        """No date in title, but content starts with a date."""
        result = extract_document_date(
            "Architecture Overview",
            "Протокол встречи от 3 февраля 2026. Участники: ...",
        )
        assert result == "2026-02-03"

    def test_content_iso_date(self) -> None:
        """Content has ISO date in first 500 chars."""
        result = extract_document_date(
            "Weekly Report",
            "Report for 2026-02-05. Key updates below.",
        )
        assert result == "2026-02-05"

    def test_content_date_beyond_500_chars_ignored(self) -> None:
        """Date beyond first 500 chars of content is not found."""
        filler = "x" * 501
        result = extract_document_date(
            "Some Page",
            filler + "2026-03-15",
            updated_at=datetime(2026, 2, 10),
        )
        # Should fallback to updated_at since date is beyond 500 chars
        assert result == "2026-02-10"


class TestTimestampFallback:
    def test_fallback_to_updated_at(self) -> None:
        """No date in title or content — use updated_at."""
        result = extract_document_date(
            "Architecture Overview",
            "No dates in this document whatsoever.",
            updated_at=datetime(2026, 2, 10),
        )
        assert result == "2026-02-10"

    def test_fallback_to_created_at(self) -> None:
        """No date in title or content, no updated_at — use created_at."""
        result = extract_document_date(
            "Architecture Overview",
            "No dates here.",
            created_at=datetime(2026, 1, 15),
        )
        assert result == "2026-01-15"

    def test_updated_at_preferred_over_created_at(self) -> None:
        """When both timestamps exist, updated_at is used."""
        result = extract_document_date(
            "Some Page",
            "No dates.",
            updated_at=datetime(2026, 2, 10),
            created_at=datetime(2026, 1, 1),
        )
        assert result == "2026-02-10"


class TestEdgeCases:
    def test_no_date_at_all(self) -> None:
        """Nothing available."""
        result = extract_document_date("Some Page", "Some text")
        assert result == ""

    def test_empty_title_and_content(self) -> None:
        result = extract_document_date("", "", updated_at=datetime(2026, 2, 5))
        assert result == "2026-02-05"

    def test_title_wins_over_timestamp(self) -> None:
        """Title date should take priority over updated_at."""
        result = extract_document_date(
            "2025-12-17 Summary",
            "Team discussed...",
            updated_at=datetime(2025, 12, 22),
        )
        assert result == "2025-12-17"

    def test_title_wins_over_content(self) -> None:
        """Title date takes priority over content date."""
        result = extract_document_date(
            "2026-01-27 Summary",
            "Meeting from 2026-02-01. Participants...",
        )
        assert result == "2026-01-27"


class TestRealCases:
    def test_summary_page_2025_12_17(self) -> None:
        """Real case: '2025-12-17 Summary' with updated_at 2025-12-22."""
        result = extract_document_date(
            "2025-12-17 Summary",
            "Team discussed...",
            updated_at=datetime(2025, 12, 22),
        )
        assert result == "2025-12-17"

    def test_weekly_summary_2026_01_27(self) -> None:
        """Real case: '2026-01-27 Summary' with updated_at 2026-02-02."""
        result = extract_document_date(
            "2026-01-27 Summary",
            "Weekly report content...",
            updated_at=datetime(2026, 2, 2),
        )
        assert result == "2026-01-27"

    def test_jira_issue_no_date_in_title(self) -> None:
        """Jira issues typically have no date in title — falls back to timestamp."""
        result = extract_document_date(
            "[MTRNIX-78] Implement Confluence connector",
            "## Description\nImplement the connector...",
            updated_at=datetime(2026, 2, 5),
        )
        assert result == "2026-02-05"

    def test_architecture_page(self) -> None:
        """Architecture pages with no dates — falls back to timestamp."""
        result = extract_document_date(
            "MTRNIX MVP - Architecture",
            "This document describes the architecture of Metatron.",
            updated_at=datetime(2026, 2, 10),
        )
        assert result == "2026-02-10"

    def test_russian_month_in_title_year_from_timestamp(self) -> None:
        """Russian month without year in title — year from updated_at."""
        result = extract_document_date(
            "Встреча 15 января",
            "Обсуждение...",
            updated_at=datetime(2026, 1, 20),
        )
        assert result == "2026-01-15"
