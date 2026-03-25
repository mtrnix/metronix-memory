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
