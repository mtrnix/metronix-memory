"""Tests for language detection in retrieval/search.py."""

from __future__ import annotations

from metronix.retrieval.search import _has_cyrillic, detect_response_language


class TestDetectResponseLanguage:
    def test_english_plain(self) -> None:
        assert detect_response_language("What is Metronix?") == "English"

    def test_russian_plain(self) -> None:
        assert detect_response_language("Что такое Metronix?") == "Russian"

    def test_mixed_mostly_english(self) -> None:
        # English question with a Russian word
        assert detect_response_language("What about задача MTRNIX-123?") == "English"

    def test_mixed_mostly_russian(self) -> None:
        # Russian question with an English word
        assert detect_response_language("Расскажи про analytics dashboard") == "Russian"

    def test_pure_latin(self) -> None:
        assert detect_response_language("show me the latest updates") == "English"

    def test_pure_cyrillic(self) -> None:
        assert detect_response_language("покажи последние обновления") == "Russian"

    def test_empty_string(self) -> None:
        # No chars of either type → defaults to English
        assert detect_response_language("") == "English"

    def test_numbers_only(self) -> None:
        assert detect_response_language("12345") == "English"

    def test_jira_key_only(self) -> None:
        assert detect_response_language("PROJ-78") == "English"

    def test_greeting_ru(self) -> None:
        assert detect_response_language("Привет!") == "Russian"

    def test_greeting_en(self) -> None:
        assert detect_response_language("Hello!") == "English"


class TestHasCyrillic:
    def test_english(self) -> None:
        assert _has_cyrillic("hello world") is False

    def test_russian(self) -> None:
        assert _has_cyrillic("привет мир") is True

    def test_mixed(self) -> None:
        assert _has_cyrillic("hello мир") is True

    def test_empty(self) -> None:
        assert _has_cyrillic("") is False

    def test_numbers(self) -> None:
        assert _has_cyrillic("12345") is False
