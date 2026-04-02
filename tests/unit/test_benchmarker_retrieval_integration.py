"""Test retrieval metrics integration in MetricsController and runner."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

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

from metatron.benchmarker.schemas.benchmark import (
    BenchmarkQuestion,
    Claim,
    QuestionAttributes,
)
from metatron.benchmarker.schemas.test_context import TestContext
from metatron.benchmarker.schemas.test_result import MetricsResult
from metatron.benchmarker.services.metrics.controller import MetricsController
from metatron.benchmarker.services.runner import TestRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_question(text: str = "What is X?") -> BenchmarkQuestion:
    return BenchmarkQuestion(
        id="q1",
        text=text,
        question_type="data_local",
        references=["ref1"],
        attributes=QuestionAttributes(
            input_question=text,
            reference_coverage=0.5,
            relevant_reference_count=1,
            reference_count=2,
            min_reference_similarity=0.1,
            max_reference_similarity=0.9,
            mean_reference_similarity=0.5,
            intra_inter_similarity_ratio=1.0,
            claim_count=1,
            claims=[Claim(statement="X is Y", sources=[], score=80, source_ids=[])],
        ),
    )


def _make_context(
    has_wb: bool = True,
    expected_labels: set[str] | None = None,
    retrieved_labels: list[str] | None = None,
) -> TestContext:
    ctx = TestContext(
        question=_make_question(),
        answer="X is a thing",
        latency_ms=100.0,
        workspace_id="ws1",
        expected_doc_labels=expected_labels,
        retrieved_doc_labels=retrieved_labels,
    )
    if has_wb:
        ctx.source_results = [{"id": "src1", "score": 0.9}]
        ctx.fragments = ["fragment text"]
        ctx.graph_entities = [{"name": "Entity1"}]
    return ctx


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestMetricsResultRetrievalFields:
    """MetricsResult can hold ndcg_at_10, mrr, precision_at_k."""

    def test_default_none(self):
        r = MetricsResult()
        assert r.ndcg_at_10 is None
        assert r.mrr is None
        assert r.precision_at_k is None

    def test_set_values(self):
        r = MetricsResult(ndcg_at_10=0.85, mrr=1.0, precision_at_k=0.6)
        assert r.ndcg_at_10 == 0.85
        assert r.mrr == 1.0
        assert r.precision_at_k == 0.6


class TestTestContextRetrievalFields:
    """TestContext can hold expected_doc_labels (set) and retrieved_doc_labels (list)."""

    def test_default_none(self):
        ctx = TestContext(
            question=_make_question(),
            answer="ans",
            latency_ms=50.0,
        )
        assert ctx.expected_doc_labels is None
        assert ctx.retrieved_doc_labels is None

    def test_set_values(self):
        ctx = TestContext(
            question=_make_question(),
            answer="ans",
            latency_ms=50.0,
            expected_doc_labels={"doc_a", "doc_b"},
            retrieved_doc_labels=["doc_b", "doc_c", "doc_a"],
        )
        assert ctx.expected_doc_labels == {"doc_a", "doc_b"}
        assert ctx.retrieved_doc_labels == ["doc_b", "doc_c", "doc_a"]


# ---------------------------------------------------------------------------
# Controller retrieval metrics
# ---------------------------------------------------------------------------


class TestControllerRetrievalMetrics:
    """When TestContext has both expected and retrieved labels, controller computes metrics."""

    @pytest.mark.asyncio
    async def test_calc_retrieval_with_labels(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        ctx = _make_context(
            expected_labels={"doc_a", "doc_b"},
            retrieved_labels=["doc_a", "doc_c", "doc_b"],
        )

        results = await controller._calc_retrieval([ctx])

        assert results is not None
        assert len(results) == 1
        r = results[0]
        assert r is not None
        assert "ndcg_at_k" in r
        assert "mrr" in r
        assert "precision_at_k" in r
        # doc_a at position 1 → mrr = 1.0
        assert r["mrr"] == 1.0
        # 2 relevant out of 3 retrieved (k=10, but only 3 docs)
        assert abs(r["precision_at_k"] - 2 / 3) < 1e-9

    @pytest.mark.asyncio
    async def test_calc_retrieval_without_labels(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        ctx = _make_context(expected_labels=None, retrieved_labels=None)

        results = await controller._calc_retrieval([ctx])

        assert results is not None
        assert len(results) == 1
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_calc_retrieval_error_returns_none(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        ctx = _make_context(
            expected_labels={"doc_a"},
            retrieved_labels=["doc_a"],
        )

        with patch.object(
            controller.retrieval,
            "compute",
            side_effect=RuntimeError("boom"),
        ):
            results = await controller._calc_retrieval([ctx])

        assert results is None

    @pytest.mark.asyncio
    async def test_calculate_all_includes_retrieval(self):
        """calculate_all merges retrieval metrics into MetricsResult."""
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        ctx = _make_context(
            expected_labels={"doc_a"},
            retrieved_labels=["doc_a", "doc_b"],
        )

        # Mock all 6 original metrics + let retrieval run for real
        with (
            patch.object(controller, "_calc_correctness", new_callable=AsyncMock) as m_corr,
            patch.object(controller, "_calc_relevancy", new_callable=AsyncMock) as m_rel,
            patch.object(controller, "_calc_faithfulness", new_callable=AsyncMock) as m_faith,
            patch.object(controller, "_calc_precision", new_callable=AsyncMock) as m_prec,
            patch.object(controller, "_calc_recall", new_callable=AsyncMock) as m_rec,
            patch.object(controller, "_calc_confidence", new_callable=AsyncMock) as m_conf,
        ):
            m_corr.return_value = None
            m_rel.return_value = None
            m_faith.return_value = None
            m_prec.return_value = None
            m_rec.return_value = None
            m_conf.return_value = None

            results = await controller.calculate_all([ctx])

        assert len(results) == 1
        r = results[0]
        assert r.ndcg_at_10 is not None
        assert r.mrr == 1.0
        assert r.precision_at_k == 0.5  # 1 relevant out of 2


# ---------------------------------------------------------------------------
# Runner: _compute_avg_metrics includes retrieval averages
# ---------------------------------------------------------------------------


class TestRunnerAvgMetricsIncludesRetrieval:
    """_compute_avg_metrics includes retrieval metric averages."""

    def test_avg_includes_retrieval_metrics(self):
        results = [
            MetricsResult(ndcg_at_10=0.8, mrr=1.0, precision_at_k=0.6),
            MetricsResult(ndcg_at_10=0.6, mrr=0.5, precision_at_k=0.4),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        assert avg["avg_ndcg_at_10"] == pytest.approx(0.7)
        assert avg["avg_mrr"] == pytest.approx(0.75)
        assert avg["avg_precision_at_k"] == pytest.approx(0.5)

    def test_avg_retrieval_none_when_all_none(self):
        results = [
            MetricsResult(ndcg_at_10=None, mrr=None, precision_at_k=None),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        assert avg["avg_ndcg_at_10"] is None
        assert avg["avg_mrr"] is None
        assert avg["avg_precision_at_k"] is None


# ---------------------------------------------------------------------------
# Runner: _run_single populates retrieved_doc_labels from trace
# ---------------------------------------------------------------------------


class TestRunnerRetrievedDocLabels:
    """_run_single populates retrieved_doc_labels from trace."""

    @pytest.mark.asyncio
    async def test_run_single_sets_retrieved_doc_labels(self):
        controller = MagicMock()
        controller.calculate_all = AsyncMock(return_value=[MetricsResult()])
        fetcher = MagicMock()
        fetcher.fetch_chunks = AsyncMock(return_value=[])

        runner = TestRunner(controller, fetcher)

        mock_trace = {
            "answer": "Paris",
            "source_results": [],
            "fragments": [],
            "graph_entities": [],
            "retrieved_doc_labels": ["doc_a", "doc_b", "doc_c"],
        }

        with patch(
            "metatron.benchmarker.services.runner.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=mock_trace,
        ):
            ctx = await runner._run_single(_make_question(), "workspace1")

        assert ctx.retrieved_doc_labels == ["doc_a", "doc_b", "doc_c"]

    @pytest.mark.asyncio
    async def test_run_single_no_retrieved_doc_labels(self):
        controller = MagicMock()
        controller.calculate_all = AsyncMock(return_value=[MetricsResult()])
        fetcher = MagicMock()
        fetcher.fetch_chunks = AsyncMock(return_value=[])

        runner = TestRunner(controller, fetcher)

        mock_trace = {
            "answer": "Paris",
            "source_results": [],
            "fragments": [],
            "graph_entities": [],
        }

        with patch(
            "metatron.benchmarker.services.runner.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=mock_trace,
        ):
            ctx = await runner._run_single(_make_question(), "workspace1")

        assert ctx.retrieved_doc_labels == []


# ---------------------------------------------------------------------------
# Additional edge cases: controller with partial labels
# ---------------------------------------------------------------------------


class TestControllerRetrievalEdgeCases:
    """Edge cases where only one of expected/retrieved labels is present."""

    @pytest.mark.asyncio
    async def test_expected_labels_but_empty_retrieved(self):
        """expected_doc_labels set but retrieved_doc_labels empty → None."""
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        ctx = _make_context(
            expected_labels={"doc_a", "doc_b"},
            retrieved_labels=[],
        )

        results = await controller._calc_retrieval([ctx])

        assert results is not None
        assert len(results) == 1
        # Empty retrieved_doc_labels is falsy → should return None
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_retrieved_labels_but_no_expected(self):
        """retrieved_doc_labels present but no expected → None."""
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        ctx = _make_context(
            expected_labels=None,
            retrieved_labels=["doc_a", "doc_b"],
        )

        results = await controller._calc_retrieval([ctx])

        assert results is not None
        assert len(results) == 1
        assert results[0] is None


# ---------------------------------------------------------------------------
# _compute_avg_metrics edge cases
# ---------------------------------------------------------------------------


class TestComputeAvgMetricsEdgeCases:
    def test_mix_of_none_and_real_retrieval_values(self):
        results = [
            MetricsResult(ndcg_at_10=0.8, mrr=1.0, precision_at_k=0.6),
            MetricsResult(ndcg_at_10=None, mrr=None, precision_at_k=None),
            MetricsResult(ndcg_at_10=0.4, mrr=0.5, precision_at_k=0.2),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        # Only 2 non-None values for retrieval metrics
        assert avg["avg_ndcg_at_10"] == pytest.approx(0.6)
        assert avg["avg_mrr"] == pytest.approx(0.75)
        assert avg["avg_precision_at_k"] == pytest.approx(0.4)

    def test_all_retrieval_fields_zero_not_none(self):
        results = [
            MetricsResult(ndcg_at_10=0.0, mrr=0.0, precision_at_k=0.0),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        # 0.0 is not None — should be included in averages
        assert avg["avg_ndcg_at_10"] == 0.0
        assert avg["avg_mrr"] == 0.0
        assert avg["avg_precision_at_k"] == 0.0
