"""Tests for ingestion/dedup.py — SimHash near-duplicate detection."""

from __future__ import annotations

from metatron.ingestion.dedup import hamming_distance, is_near_duplicate, simhash


class TestSimhash:
    def test_empty_text_returns_zero(self) -> None:
        assert simhash("") == 0
        assert simhash("   ") == 0

    def test_identical_texts_same_hash(self) -> None:
        text = "The quick brown fox jumps over the lazy dog"
        assert simhash(text) == simhash(text)

    def test_different_texts_different_hash(self) -> None:
        h1 = simhash("The quick brown fox jumps over the lazy dog")
        h2 = simhash("A completely different sentence about something else entirely")
        assert h1 != h2

    def test_similar_texts_close_hash(self) -> None:
        h1 = simhash("The quick brown fox jumps over the lazy dog")
        h2 = simhash("The quick brown fox leaps over the lazy dog")
        # Similar texts should have smaller Hamming distance than random
        assert hamming_distance(h1, h2) < 32

    def test_hash_is_integer(self) -> None:
        h = simhash("Some text content")
        assert isinstance(h, int)
        assert h >= 0


class TestHammingDistance:
    def test_identical_hashes(self) -> None:
        assert hamming_distance(0, 0) == 0
        assert hamming_distance(42, 42) == 0

    def test_single_bit_difference(self) -> None:
        assert hamming_distance(0b0000, 0b0001) == 1
        assert hamming_distance(0b1000, 0b0000) == 1

    def test_all_bits_different(self) -> None:
        assert hamming_distance(0, 0xFFFFFFFFFFFFFFFF) == 64

    def test_known_distance(self) -> None:
        # 0b1010 vs 0b0101 = 4 bits different
        assert hamming_distance(0b1010, 0b0101) == 4


class TestIsNearDuplicate:
    def test_identical_texts_are_duplicates(self) -> None:
        h1 = simhash("The quick brown fox")
        h2 = simhash("The quick brown fox")
        assert is_near_duplicate(h1, h2) is True

    def test_similar_texts_are_duplicates(self) -> None:
        h1 = simhash("The quick brown fox jumps over the lazy dog")
        h2 = simhash("The quick brown fox jumps over the lazy cat")
        # These should be close enough with default threshold
        assert is_near_duplicate(h1, h2, threshold=10) is True

    def test_different_texts_not_duplicates(self) -> None:
        h1 = simhash("Python programming language features")
        h2 = simhash("Cooking recipes for Italian pasta dishes")
        assert is_near_duplicate(h1, h2, threshold=3) is False

    def test_custom_threshold(self) -> None:
        h1 = simhash("Hello world example")
        h2 = simhash("Hello world sample")
        dist = hamming_distance(h1, h2)
        assert is_near_duplicate(h1, h2, threshold=dist) is True
        assert is_near_duplicate(h1, h2, threshold=dist - 1) is False
