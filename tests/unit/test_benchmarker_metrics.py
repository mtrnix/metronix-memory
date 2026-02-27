"""Tests for MetricsController — orchestrate parallel metric computation.

Tests:
- Initialization via from_settings()
- Parallel metric computation via asyncio.gather()
- Error handling for individual metrics (return None)
- Mocks for DeepSeek API, Embedding Proxy, BenchmarkQED
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.benchmarker.schemas.benchmark import (
    BenchmarkQuestion,
    Claim,
    QuestionAttributes,
)
from metatron.benchmarker.schemas.test_context import TestContext
from metatron.benchmarker.schemas.test_result import ConfidenceResult, MetricsResult
from metatron.benchmarker.services.metrics.controller import MetricsController
from metatron.core.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        METATRON_SECRET_KEY="test",
        POSTGRES_HOST="localhost",
        POSTGRES_PASSWORD="test",
        FERNET_KEY="",
        DEEPSEEK_API_KEY="test-key",
        DEEPSEEK_MODEL="deepseek-chat",
        BENCHMARKER_EMBEDDING_PROXY_URL="http://localhost:8001",
        OLLAMA_EMBED_MODEL="nomic-embed-text",
    )


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
    question_text: str = "What is X?",
    answer: str = "X is a thing",
    has_wb: bool = True,
) -> TestContext:
    ctx = TestContext(
        question=_make_question(question_text),
        answer=answer,
        latency_ms=100.0,
        workspace_id="ws1",
    )
    if has_wb:
        ctx.source_results = [{"id": "src1", "score": 0.9}]
        ctx.fragments = ["fragment text"]
        ctx.graph_entities = [{"name": "Entity1"}]
    return ctx


# ---------------------------------------------------------------------------
# from_settings()
# ---------------------------------------------------------------------------


class TestFromSettings:
    def test_creates_controller_from_settings(self):
        settings = _make_settings()
        controller = MetricsController.from_settings(settings)

        assert controller is not None
        assert controller.qed is not None
        assert controller.relevancy is not None
        assert controller.faithfulness is not None
        assert controller.precision is not None
        assert controller.recall is not None
        assert controller.confidence is not None


# ---------------------------------------------------------------------------
# calculate_all — parallel computation
# ---------------------------------------------------------------------------


class TestCalculateAll:
    @pytest.mark.asyncio
    async def test_empty_contexts_returns_empty(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        results = await controller.calculate_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_metrics_result_per_context(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        contexts = [_make_context(), _make_context("Q2?")]

        # Mock all 6 metric calculators
        with patch.object(controller, "_calc_correctness", new_callable=AsyncMock) as m_corr, \
             patch.object(controller, "_calc_relevancy", new_callable=AsyncMock) as m_rel, \
             patch.object(controller, "_calc_faithfulness", new_callable=AsyncMock) as m_faith, \
             patch.object(controller, "_calc_precision", new_callable=AsyncMock) as m_prec, \
             patch.object(controller, "_calc_recall", new_callable=AsyncMock) as m_rec, \
             patch.object(controller, "_calc_confidence", new_callable=AsyncMock) as m_conf:

            m_corr.return_value = [{"score": 0.8, "claim_scores": []}, {"score": 0.7, "claim_scores": []}]
            m_rel.return_value = [MagicMock(score=0.9), MagicMock(score=0.85)]
            m_faith.return_value = [MagicMock(score=0.75, reasoning="ok"), MagicMock(score=0.8, reasoning="good")]
            m_prec.return_value = [MagicMock(score=0.6, chunk_scores=[0.5]), MagicMock(score=0.7, chunk_scores=[0.6])]
            m_rec.return_value = [MagicMock(score=0.5, reasoning="r"), MagicMock(score=0.6, reasoning="r2")]
            m_conf.return_value = [MagicMock(score=1.0), MagicMock(score=1.0)]

            results = await controller.calculate_all(contexts)

        assert len(results) == 2
        for r in results:
            assert isinstance(r, MetricsResult)

    @pytest.mark.asyncio
    async def test_all_six_metrics_called(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        contexts = [_make_context()]

        with patch.object(controller, "_calc_correctness", new_callable=AsyncMock) as m_corr, \
             patch.object(controller, "_calc_relevancy", new_callable=AsyncMock) as m_rel, \
             patch.object(controller, "_calc_faithfulness", new_callable=AsyncMock) as m_faith, \
             patch.object(controller, "_calc_precision", new_callable=AsyncMock) as m_prec, \
             patch.object(controller, "_calc_recall", new_callable=AsyncMock) as m_rec, \
             patch.object(controller, "_calc_confidence", new_callable=AsyncMock) as m_conf:

            m_corr.return_value = None
            m_rel.return_value = None
            m_faith.return_value = None
            m_prec.return_value = None
            m_rec.return_value = None
            m_conf.return_value = None

            await controller.calculate_all(contexts)

        m_corr.assert_awaited_once()
        m_rel.assert_awaited_once()
        m_faith.assert_awaited_once()
        m_prec.assert_awaited_once()
        m_rec.assert_awaited_once()
        m_conf.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error handling — individual metrics return None
# ---------------------------------------------------------------------------


class TestMetricErrorHandling:
    @pytest.mark.asyncio
    async def test_correctness_error_returns_none(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )

        with patch.object(controller.qed, "evaluate_answers", new_callable=AsyncMock) as mock_eval:
            mock_eval.side_effect = RuntimeError("QED unavailable")

            result = await controller._calc_correctness([_make_context()])

        assert result is None

    @pytest.mark.asyncio
    async def test_relevancy_error_returns_none(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )

        with patch.object(controller.relevancy, "calculate_batch", new_callable=AsyncMock) as mock_rel:
            mock_rel.side_effect = RuntimeError("Embedding proxy down")

            result = await controller._calc_relevancy([_make_context()])

        assert result is None

    @pytest.mark.asyncio
    async def test_faithfulness_error_returns_none(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )

        with patch.object(controller.faithfulness, "calculate_batch", new_callable=AsyncMock) as mock_faith:
            mock_faith.side_effect = RuntimeError("DeepSeek error")

            result = await controller._calc_faithfulness([_make_context()])

        assert result is None

    @pytest.mark.asyncio
    async def test_confidence_error_returns_none(self):
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )

        with patch.object(controller.confidence, "calculate_batch", new_callable=AsyncMock) as mock_conf:
            mock_conf.side_effect = RuntimeError("Confidence error")

            result = await controller._calc_confidence([_make_context()])

        assert result is None

    @pytest.mark.asyncio
    async def test_partial_failure_still_returns_results(self):
        """If one metric fails, others still produce values."""
        controller = MetricsController(
            deepseek_api_key="key",
            embedding_base_url="http://localhost:8001",
        )
        contexts = [_make_context()]

        with patch.object(controller, "_calc_correctness", new_callable=AsyncMock) as m_corr, \
             patch.object(controller, "_calc_relevancy", new_callable=AsyncMock) as m_rel, \
             patch.object(controller, "_calc_faithfulness", new_callable=AsyncMock) as m_faith, \
             patch.object(controller, "_calc_precision", new_callable=AsyncMock) as m_prec, \
             patch.object(controller, "_calc_recall", new_callable=AsyncMock) as m_rec, \
             patch.object(controller, "_calc_confidence", new_callable=AsyncMock) as m_conf:

            # Correctness fails, others succeed
            m_corr.return_value = None
            m_rel.return_value = [MagicMock(score=0.9)]
            m_faith.return_value = None
            m_prec.return_value = None
            m_rec.return_value = None
            m_conf.return_value = [MagicMock(score=1.0)]

            results = await controller.calculate_all(contexts)

        assert len(results) == 1
        r = results[0]
        assert r.correctness is None
        assert r.answer_relevancy == 0.9
        assert r.confidence == 1.0


# ---------------------------------------------------------------------------
# _safe_get helper
# ---------------------------------------------------------------------------


class TestSafeGet:
    def test_none_results(self):
        assert MetricsController._safe_get(None, 0, "score") is None

    def test_index_out_of_range(self):
        assert MetricsController._safe_get([{"score": 1}], 5, "score") is None

    def test_none_item(self):
        assert MetricsController._safe_get([None], 0, "score") is None

    def test_dict_item(self):
        assert MetricsController._safe_get([{"score": 0.8}], 0, "score") == 0.8

    def test_object_item(self):
        obj = MagicMock(score=0.7)
        assert MetricsController._safe_get([obj], 0, "score") == 0.7
