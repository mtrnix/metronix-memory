"""Tests for deterministic retrieval metrics: Precision@K, MRR, NDCG@K."""
from __future__ import annotations

import math
import sys
from unittest.mock import MagicMock

import pytest

# benchmark_qed is an optional dependency that may not be installed.
# Stub the entire package tree so importing the metrics package succeeds.
if "benchmark_qed" not in sys.modules:
    _mock = MagicMock()
    for _name in [
        "benchmark_qed",
        "benchmark_qed.autoe",
        "benchmark_qed.autoe.assertion_scores",
        "benchmark_qed.autod",
        "benchmark_qed.autod.data_model",
        "benchmark_qed.autod.data_model.text_unit",
        "benchmark_qed.autod.data_processor",
        "benchmark_qed.autod.data_processor.embedding",
        "benchmark_qed.autod.sampler",
        "benchmark_qed.autod.sampler.clustering",
        "benchmark_qed.autod.sampler.clustering.kmeans",
        "benchmark_qed.autoq",
        "benchmark_qed.autoq.data_model",
        "benchmark_qed.autoq.data_model.question",
        "benchmark_qed.autoq.question_gen",
        "benchmark_qed.autoq.question_gen.data_questions",
        "benchmark_qed.autoq.question_gen.data_questions.global_question_gen",
        "benchmark_qed.autoq.question_gen.data_questions.local_question_gen",
        "benchmark_qed.autoq.question_generator",
        "benchmark_qed.config",
        "benchmark_qed.config.llm_config",
        "benchmark_qed.llm",
        "benchmark_qed.llm.provider",
        "benchmark_qed.llm.provider.openai",
    ]:
        sys.modules[_name] = _mock

from metatron.benchmarker.services.metrics.retrieval import (
    RetrievalMetrics,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
)

# ---------------------------------------------------------------------------
# precision_at_k
# ---------------------------------------------------------------------------

class TestPrecisionAtK:
    def test_all_relevant(self):
        assert precision_at_k(["d1", "d2", "d3"], {"d1", "d2", "d3"}, k=3) == 1.0

    def test_none_relevant(self):
        assert precision_at_k(["d4", "d5", "d6"], {"d1", "d2", "d3"}, k=3) == 0.0

    def test_partial_relevant(self):
        assert precision_at_k(["d1", "d4", "d3"], {"d1", "d2", "d3"}, k=3) == pytest.approx(2 / 3)

    def test_k_larger_than_retrieved(self):
        # denominator should be len(retrieved)=2, not k=5
        assert precision_at_k(["d1", "d2"], {"d1", "d2", "d3"}, k=5) == 1.0

    def test_empty_retrieved(self):
        assert precision_at_k([], {"d1", "d2"}, k=3) == 0.0

    def test_empty_expected(self):
        assert precision_at_k(["d1", "d2"], set(), k=3) == 0.0

    def test_k_truncates_list(self):
        # Only first 2 considered; d3 is relevant but beyond k
        assert precision_at_k(["d1", "d4", "d3"], {"d1", "d3"}, k=2) == pytest.approx(1 / 2)

    def test_k_one(self):
        assert precision_at_k(["d1", "d2"], {"d1"}, k=1) == 1.0
        assert precision_at_k(["d2", "d1"], {"d1"}, k=1) == 0.0


# ---------------------------------------------------------------------------
# mean_reciprocal_rank
# ---------------------------------------------------------------------------

class TestMeanReciprocalRank:
    def test_first_relevant(self):
        assert mean_reciprocal_rank(["d1", "d2", "d3"], {"d1"}) == 1.0

    def test_second_relevant(self):
        assert mean_reciprocal_rank(["d4", "d1", "d3"], {"d1"}) == 0.5

    def test_third_relevant(self):
        assert mean_reciprocal_rank(["d4", "d5", "d1"], {"d1"}) == pytest.approx(1 / 3)

    def test_none_relevant(self):
        assert mean_reciprocal_rank(["d4", "d5", "d6"], {"d1"}) == 0.0

    def test_empty_retrieved(self):
        assert mean_reciprocal_rank([], {"d1"}) == 0.0

    def test_empty_expected(self):
        assert mean_reciprocal_rank(["d1", "d2"], set()) == 0.0

    def test_multiple_relevant_returns_first(self):
        # d2 is at rank 2, d3 at rank 3 — should return 1/2
        assert mean_reciprocal_rank(["d4", "d2", "d3"], {"d2", "d3"}) == 0.5


# ---------------------------------------------------------------------------
# ndcg_at_k
# ---------------------------------------------------------------------------

class TestNdcgAtK:
    def test_perfect_ranking(self):
        assert ndcg_at_k(["d1", "d2", "d3"], {"d1", "d2", "d3"}, k=3) == 1.0

    def test_no_relevant(self):
        assert ndcg_at_k(["d4", "d5", "d6"], {"d1", "d2", "d3"}, k=3) == 0.0

    def test_reversed_ranking(self):
        retrieved = ["d4", "d5", "d1", "d2", "d3"]
        expected = {"d1", "d2", "d3"}
        k = 5
        # DCG = 1/log2(4) + 1/log2(5) + 1/log2(6)
        dcg = 1 / math.log2(4) + 1 / math.log2(5) + 1 / math.log2(6)
        # IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4)
        idcg = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
        expected_ndcg = dcg / idcg
        assert ndcg_at_k(retrieved, expected, k) == pytest.approx(expected_ndcg, abs=1e-4)

    def test_single_relevant_at_top(self):
        assert ndcg_at_k(["d1", "d4", "d5"], {"d1"}, k=3) == 1.0

    def test_empty_retrieved(self):
        assert ndcg_at_k([], {"d1"}, k=3) == 0.0

    def test_empty_expected(self):
        assert ndcg_at_k(["d1", "d2"], set(), k=3) == 0.0

    def test_k_truncates(self):
        # d3 is relevant but at position 3, beyond k=2
        retrieved = ["d4", "d5", "d3"]
        expected = {"d3"}
        assert ndcg_at_k(retrieved, expected, k=2) == 0.0


# ---------------------------------------------------------------------------
# RetrievalMetrics
# ---------------------------------------------------------------------------

class TestRetrievalMetrics:
    def setup_method(self):
        self.metrics = RetrievalMetrics()

    def test_compute_returns_all_keys(self):
        result = self.metrics.compute(["d1", "d2"], {"d1"}, k=5)
        assert "precision_at_k" in result
        assert "mrr" in result
        assert "ndcg_at_k" in result
        assert "k" in result
        assert result["k"] == 5

    def test_compute_values(self):
        result = self.metrics.compute(["d1", "d2", "d3"], {"d1", "d2"}, k=3)
        assert result["precision_at_k"] == pytest.approx(2 / 3)
        assert result["mrr"] == 1.0
        assert result["k"] == 3

    def test_compute_batch(self):
        pairs = [
            (["d1", "d2"], {"d1"}),
            (["d3", "d4"], {"d4"}),
        ]
        results = self.metrics.compute_batch(pairs, k=2)
        assert len(results) == 2
        assert results[0]["precision_at_k"] == pytest.approx(1 / 2)
        assert results[1]["mrr"] == 0.5

    def test_compute_averages(self):
        pairs = [
            (["d1", "d2"], {"d1"}),  # p@2=0.5, mrr=1.0
            (["d3", "d4"], {"d3"}),  # p@2=0.5, mrr=1.0
        ]
        avgs = self.metrics.compute_averages(pairs, k=2)
        assert "avg_precision_at_k" in avgs
        assert "avg_mrr" in avgs
        assert "avg_ndcg_at_k" in avgs
        assert avgs["avg_precision_at_k"] == pytest.approx(0.5)
        assert avgs["avg_mrr"] == pytest.approx(1.0)

    def test_compute_averages_empty(self):
        avgs = self.metrics.compute_averages([], k=5)
        assert avgs["avg_precision_at_k"] == 0.0
        assert avgs["avg_mrr"] == 0.0
        assert avgs["avg_ndcg_at_k"] == 0.0

    def test_compute_deduplicates_retrieved(self):
        """Duplicate doc_labels should not inflate scores."""
        # d1 appears 5 times — should count as 1 hit, not 5
        retrieved = ["d1", "d1", "d1", "d1", "d1", "d2", "d3"]
        expected = {"d1", "d2"}
        result = self.metrics.compute(retrieved, expected, k=10)
        # After dedup: ["d1", "d2", "d3"] → P@3 = 2/3, MRR=1.0, NDCG≤1.0
        assert result["precision_at_k"] == pytest.approx(2 / 3)
        assert result["mrr"] == 1.0
        assert result["ndcg_at_k"] <= 1.0
        assert result["ndcg_at_k"] == 1.0  # both relevant at top


# ---------------------------------------------------------------------------
# Edge / negative cases: precision_at_k
# ---------------------------------------------------------------------------


class TestPrecisionAtKEdgeCases:
    def test_k_zero_returns_zero(self):
        assert precision_at_k(["d1", "d2"], {"d1"}, k=0) == 0.0

    def test_negative_k_returns_zero(self):
        assert precision_at_k(["d1", "d2"], {"d1"}, k=-5) == 0.0

    def test_all_duplicates_same_doc(self):
        # After slicing, all items are "d1"
        assert precision_at_k(["d1", "d1", "d1"], {"d1"}, k=3) == 1.0

    def test_very_large_k_small_list(self):
        # k=1000 but only 2 retrieved — denominator should be 2
        assert precision_at_k(["d1", "d2"], {"d1", "d2"}, k=1000) == 1.0

    def test_single_match(self):
        assert precision_at_k(["d1"], {"d1"}, k=1) == 1.0

    def test_single_no_match(self):
        assert precision_at_k(["d2"], {"d1"}, k=1) == 0.0

    def test_expected_contains_items_never_retrieved(self):
        # Expected has d3, d4 which are never in retrieved
        assert precision_at_k(["d1", "d2"], {"d1", "d3", "d4"}, k=2) == pytest.approx(1 / 2)

    def test_unicode_doc_labels(self):
        assert precision_at_k(["документ_1", "doc_2"], {"документ_1"}, k=2) == pytest.approx(1 / 2)


# ---------------------------------------------------------------------------
# Edge / negative cases: mean_reciprocal_rank
# ---------------------------------------------------------------------------


class TestMRREdgeCases:
    def test_single_item_match_at_position_1(self):
        assert mean_reciprocal_rank(["d1"], {"d1"}) == 1.0

    def test_relevant_at_position_100(self):
        retrieved = [f"d{i}" for i in range(1, 101)]
        expected = {"d100"}
        assert mean_reciprocal_rank(retrieved, expected) == pytest.approx(1 / 100)

    def test_all_retrieved_relevant(self):
        # First relevant doc is at position 1 → MRR = 1.0
        assert mean_reciprocal_rank(["d1", "d2", "d3"], {"d1", "d2", "d3"}) == 1.0

    def test_unicode_doc_labels(self):
        assert mean_reciprocal_rank(["αβγ", "δεζ"], {"δεζ"}) == 0.5


# ---------------------------------------------------------------------------
# Edge / negative cases: ndcg_at_k
# ---------------------------------------------------------------------------


class TestNdcgAtKEdgeCases:
    def test_k_zero_returns_zero(self):
        assert ndcg_at_k(["d1", "d2"], {"d1"}, k=0) == 0.0

    def test_k_one_relevant_at_top(self):
        assert ndcg_at_k(["d1", "d2"], {"d1"}, k=1) == 1.0

    def test_k_one_irrelevant_at_top(self):
        assert ndcg_at_k(["d2", "d1"], {"d1"}, k=1) == 0.0

    def test_large_k_all_relevant(self):
        labels = [f"d{i}" for i in range(20)]
        expected = set(labels)
        assert ndcg_at_k(labels, expected, k=100) == pytest.approx(1.0)

    def test_relevant_at_every_other_position(self):
        # Relevant at positions 0, 2, 4 (0-indexed) i.e. 1, 3, 5 (1-indexed)
        retrieved = ["d1", "x1", "d2", "x2", "d3", "x3"]
        expected = {"d1", "d2", "d3"}
        result = ndcg_at_k(retrieved, expected, k=6)
        # DCG = 1/log2(2) + 1/log2(4) + 1/log2(6)
        dcg = 1 / math.log2(2) + 1 / math.log2(4) + 1 / math.log2(6)
        # IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4)
        idcg = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
        assert result == pytest.approx(dcg / idcg, abs=1e-6)

    def test_expected_has_more_items_than_k(self):
        # Expected has 5 items but k=2 — IDCG should use min(5, 2)=2
        retrieved = ["d1", "d2", "d3", "d4", "d5"]
        expected = {"d1", "d2", "d3", "d4", "d5"}
        result = ndcg_at_k(retrieved, expected, k=2)
        assert result == 1.0


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------


class TestDeduplicate:
    def test_empty_list(self):
        from metatron.benchmarker.services.metrics.retrieval import _deduplicate
        assert _deduplicate([]) == []

    def test_no_duplicates(self):
        from metatron.benchmarker.services.metrics.retrieval import _deduplicate
        assert _deduplicate(["a", "b", "c"]) == ["a", "b", "c"]

    def test_all_duplicates(self):
        from metatron.benchmarker.services.metrics.retrieval import _deduplicate
        assert _deduplicate(["a", "a", "a"]) == ["a"]

    def test_preserves_order(self):
        from metatron.benchmarker.services.metrics.retrieval import _deduplicate
        assert _deduplicate(["c", "b", "a", "b", "c"]) == ["c", "b", "a"]

    def test_mixed_duplicates(self):
        from metatron.benchmarker.services.metrics.retrieval import _deduplicate
        assert _deduplicate(["a", "b", "a", "c", "b", "d"]) == ["a", "b", "c", "d"]


# ---------------------------------------------------------------------------
# RetrievalMetrics — additional edge cases
# ---------------------------------------------------------------------------


class TestRetrievalMetricsEdgeCases:
    def setup_method(self):
        self.metrics = RetrievalMetrics()

    def test_compute_all_empty_inputs(self):
        result = self.metrics.compute([], set(), k=5)
        assert result["precision_at_k"] == 0.0
        assert result["mrr"] == 0.0
        assert result["ndcg_at_k"] == 0.0
        assert result["k"] == 5.0

    def test_compute_batch_empty_list(self):
        results = self.metrics.compute_batch([], k=5)
        assert results == []

    def test_compute_batch_mixed_results(self):
        pairs = [
            (["d1"], {"d1"}),        # perfect match
            (["d2"], {"d1"}),        # zero match
        ]
        results = self.metrics.compute_batch(pairs, k=5)
        assert len(results) == 2
        assert results[0]["precision_at_k"] == 1.0
        assert results[0]["mrr"] == 1.0
        assert results[1]["precision_at_k"] == 0.0
        assert results[1]["mrr"] == 0.0

    def test_compute_averages_single_pair(self):
        pairs = [(["d1", "d2"], {"d1"})]
        avgs = self.metrics.compute_averages(pairs, k=2)
        assert avgs["avg_precision_at_k"] == pytest.approx(0.5)
        assert avgs["avg_mrr"] == 1.0

    def test_ndcg_never_exceeds_one_with_duplicated_retrieved(self):
        """After dedup, NDCG should never exceed 1.0."""
        retrieved = ["d1", "d1", "d1", "d2", "d2", "d3"]
        expected = {"d1", "d2", "d3"}
        result = self.metrics.compute(retrieved, expected, k=10)
        assert result["ndcg_at_k"] <= 1.0
        assert result["ndcg_at_k"] == pytest.approx(1.0)
