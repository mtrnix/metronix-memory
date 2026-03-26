"""Tests for retrieval/scoring.py — multi-signal scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from metatron.retrieval.scoring import (
    compute_final_score,
    compute_signal_score,
    normalize_rerank_scores,
    recency_score,
    source_balance,
)


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


class TestSourceBalance:
    def test_underrepresented_gets_bonus(self) -> None:
        type_counts = {"jira": 5, "confluence": 1}
        total = 6
        assert source_balance("confluence", type_counts, total) == 1.0

    def test_overrepresented_gets_zero(self) -> None:
        type_counts = {"jira": 5, "confluence": 1}
        total = 6
        assert source_balance("jira", type_counts, total) == 0.0

    def test_even_split_still_over_threshold(self) -> None:
        type_counts = {"jira": 3, "confluence": 3}
        total = 6
        assert source_balance("jira", type_counts, total) == 0.0

    def test_three_types_balanced(self) -> None:
        type_counts = {"jira": 2, "confluence": 2, "upload": 2}
        total = 6
        assert source_balance("jira", type_counts, total) == 1.0

    def test_empty_pool(self) -> None:
        assert source_balance("jira", {}, 0) == 1.0


class TestComputeSignalScore:
    def test_all_signals_present(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 0.8, "graph": 0.6, "exact": 0.7},
            recency=0.9,
            balance=1.0,
        )
        raw = 0.35*0.8 + 0.15*0.6 + 0.20*0.7 + 0.10*0.9 + 0.05*1.0
        expected = raw / 0.85
        assert abs(score - expected) < 0.001

    def test_dense_only(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0},
            recency=0.0,
            balance=0.0,
        )
        expected = (0.35 * 1.0) / 0.85
        assert abs(score - expected) < 0.001

    def test_no_channels(self) -> None:
        score = compute_signal_score(
            channel_scores={},
            recency=1.0,
            balance=1.0,
        )
        expected = (0.10 * 1.0 + 0.05 * 1.0) / 0.85
        assert abs(score - expected) < 0.001

    def test_custom_weights(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0},
            recency=0.0,
            balance=0.0,
            dense_weight=0.5,
            sparse_weight=0.0,
            graph_weight=0.1,
            metadata_weight=0.1,
            recency_weight=0.1,
            balance_weight=0.1,
        )
        expected = 0.5 / 0.9
        assert abs(score - expected) < 0.001

    def test_output_in_zero_one_range(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0, "graph": 1.0, "exact": 1.0, "metadata": 1.0},
            recency=1.0,
            balance=1.0,
        )
        assert 0.0 <= score <= 1.0


class TestNormalizeRerankScores:
    def test_basic_normalization(self) -> None:
        results = [
            {"rerank_score": 5.0},
            {"rerank_score": 3.0},
            {"rerank_score": 1.0},
        ]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0
        assert results[2]["rerank_score"] == 0.0
        assert abs(results[1]["rerank_score"] - 0.5) < 0.01

    def test_all_same_score(self) -> None:
        results = [
            {"rerank_score": 3.0},
            {"rerank_score": 3.0},
        ]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0
        assert results[1]["rerank_score"] == 1.0

    def test_single_result(self) -> None:
        results = [{"rerank_score": -2.0}]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0

    def test_negative_scores(self) -> None:
        results = [
            {"rerank_score": -1.0},
            {"rerank_score": -3.0},
        ]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0
        assert results[1]["rerank_score"] == 0.0

    def test_empty_list(self) -> None:
        normalize_rerank_scores([])  # should not raise


class TestComputeFinalScore:
    def test_default_blend(self) -> None:
        score = compute_final_score(signal_score=1.0, rerank_score=0.0)
        assert abs(score - 0.3) < 0.01

    def test_full_rerank(self) -> None:
        score = compute_final_score(signal_score=0.0, rerank_score=1.0)
        assert abs(score - 0.7) < 0.01

    def test_custom_blend(self) -> None:
        score = compute_final_score(signal_score=0.8, rerank_score=0.6, blend_weight=0.5)
        assert abs(score - 0.7) < 0.01

    def test_equal_scores(self) -> None:
        score = compute_final_score(signal_score=0.5, rerank_score=0.5)
        assert abs(score - 0.5) < 0.01
