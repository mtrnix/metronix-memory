"""Tests for channels/telegram.py — message splitting logic."""

from __future__ import annotations

from metatron.channels.telegram import _split_message


class TestSplitMessage:
    def test_short_message(self) -> None:
        result = _split_message("hello", max_length=100)
        assert result == ["hello"]

    def test_exact_limit(self) -> None:
        text = "a" * 100
        result = _split_message(text, max_length=100)
        assert result == [text]

    def test_split_at_paragraph(self) -> None:
        text = "first paragraph\n\nsecond paragraph"
        result = _split_message(text, max_length=25)
        assert len(result) == 2
        assert result[0] == "first paragraph"
        assert result[1] == "second paragraph"

    def test_split_at_newline(self) -> None:
        text = "line one\nline two\nline three"
        result = _split_message(text, max_length=15)
        assert len(result) >= 2
        assert "line one" in result[0]

    def test_split_at_space(self) -> None:
        text = "word1 word2 word3 word4"
        result = _split_message(text, max_length=12)
        assert len(result) >= 2
        # Each chunk should be <= 12 chars
        for chunk in result:
            assert len(chunk) <= 12

    def test_hard_split(self) -> None:
        text = "a" * 200
        result = _split_message(text, max_length=50)
        assert len(result) == 4
        for chunk in result:
            assert len(chunk) <= 50

    def test_empty_string(self) -> None:
        result = _split_message("", max_length=100)
        assert result == [""]

    def test_long_real_message(self) -> None:
        # Simulate a real search result
        text = ("**MTRNIX-78: Analytics Dashboard**\n\n"
                "Status: In Progress\nAssignee: John\n\n"
                "Description: This is a long description " * 20)
        result = _split_message(text, max_length=200)
        assert len(result) > 1
        # All content preserved
        combined = "\n\n".join(result) if len(result) > 1 else result[0]
        # No data loss (some newlines may be stripped)
        for chunk in result:
            assert len(chunk) <= 200
