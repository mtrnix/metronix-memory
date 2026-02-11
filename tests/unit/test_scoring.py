"""Tests for retrieval/scoring.py — multi-factor scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from metatron.retrieval.scoring import (
    multi_factor_score,
    recency_score,
    tag_match,
    token_overlap,
)


class TestTokenOverlap:
    def test_identical_tokens(self) -> None:
        tokens = ["hello", "world"]
        assert token_overlap(tokens, tokens) == 1.0

    def test_no_overlap(self) -> None:
        assert token_overlap(["hello"], ["world"]) == 0.0

    def test_partial_overlap(self) -> None:
        query = ["hello", "world"]
        chunk = ["hello", "there"]
        result = token_overlap(query, chunk)
        # intersection={"hello"}, union={"hello","world","there"}
        assert abs(result - 1 / 3) < 0.01

    def test_empty_inputs(self) -> None:
        assert token_overlap([], ["hello"]) == 0.0
        assert token_overlap(["hello"], []) == 0.0
        assert token_overlap([], []) == 0.0


class TestTagMatch:
    def test_full_match(self) -> None:
        assert tag_match(["python", "api"], ["python", "api", "docs"]) == 1.0

    def test_no_match(self) -> None:
        assert tag_match(["python"], ["java"]) == 0.0

    def test_partial_match(self) -> None:
        result = tag_match(["python", "api"], ["python", "docs"])
        assert abs(result - 0.5) < 0.01

    def test_case_insensitive(self) -> None:
        assert tag_match(["Python"], ["python"]) == 1.0

    def test_empty_inputs(self) -> None:
        assert tag_match([], ["python"]) == 0.0
        assert tag_match(["python"], []) == 0.0


class TestRecencyScore:
    def test_just_now(self) -> None:
        now = datetime.now(timezone.utc)
        score = recency_score(now, now)
        assert abs(score - 1.0) < 0.01

    def test_half_life(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=30)
        score = recency_score(past, now, half_life_days=30)
        assert abs(score - 0.5) < 0.01

    def test_very_old(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=365)
        score = recency_score(past, now, half_life_days=30)
        assert score < 0.01

    def test_score_between_zero_and_one(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=15)
        score = recency_score(past, now)
        assert 0.0 < score <= 1.0


class TestMultiFactorScore:
    def test_all_zeros(self) -> None:
        score = multi_factor_score(0.0, 0.0, 0.0, 0.0, 0.0)
        assert score == 0.0

    def test_all_ones(self) -> None:
        score = multi_factor_score(1.0, 1.0, 1.0, 1.0, 1.0)
        assert abs(score - 1.0) < 0.01

    def test_weights_sum_to_one(self) -> None:
        # With all signals = 1.0, result should be 1.0
        score = multi_factor_score(
            1.0, 1.0, 1.0, 1.0, 1.0,
            dense_weight=0.35,
            sparse_weight=0.20,
            tag_weight=0.20,
            graph_weight=0.15,
            recency_weight=0.10,
        )
        assert abs(score - 1.0) < 0.01

    def test_dense_dominates(self) -> None:
        # Dense-only signal should give 0.35
        score = multi_factor_score(1.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(score - 0.35) < 0.01

    def test_custom_weights(self) -> None:
        score = multi_factor_score(
            1.0, 0.0, 0.0, 0.0, 0.0,
            dense_weight=0.5,
        )
        assert abs(score - 0.5) < 0.01
