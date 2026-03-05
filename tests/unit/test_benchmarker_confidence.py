"""Tests for ConfidenceMetric — response consistency via embedding similarity.

Validates Property 9: ConfidenceMetric.calculate_batch() returns a list of
ConfidenceResult with the same length as the input, with scores in [0, 1].
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.benchmarker.schemas.test_result import ConfidenceResult
from metatron.benchmarker.services.metrics.confidence import ConfidenceMetric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metric() -> ConfidenceMetric:
    """Create a ConfidenceMetric with test defaults."""
    return ConfidenceMetric(
        embedding_base_url="http://localhost:8001",
        embedding_model="nomic-embed-text",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfidenceMetricEmptyList:
    """Confidence with an empty question list."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        metric = _make_metric()
        results = await metric.calculate_batch([], workspace_id="ws1")
        assert results == []


class TestConfidenceMetricSingleItem:
    """Confidence with a single question."""

    @pytest.mark.asyncio
    async def test_single_question_returns_one_result(self):
        metric = _make_metric()

        with patch.object(metric, "_calculate_single", new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = ConfidenceResult(score=0.95, avg_similarity=0.9, num_responses=5)
            results = await metric.calculate_batch(["What is X?"], workspace_id="ws1")

        assert len(results) == 1
        assert isinstance(results[0], ConfidenceResult)
        assert results[0].score == 0.95


class TestConfidenceMetricMultipleItems:
    """Confidence with multiple questions."""

    @pytest.mark.asyncio
    async def test_multiple_questions_returns_matching_length(self):
        metric = _make_metric()
        questions = ["Q1?", "Q2?", "Q3?"]

        with patch.object(metric, "_calculate_single", new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = ConfidenceResult(score=0.8, avg_similarity=0.6, num_responses=5)
            results = await metric.calculate_batch(questions, workspace_id="ws1")

        assert len(results) == len(questions)
        for r in results:
            assert isinstance(r, ConfidenceResult)
            assert r.score == 0.8


class TestConfidenceMetricCalculateSingle:
    """Test _calculate_single with mocked RAG and embedding calls."""

    @pytest.mark.asyncio
    async def test_returns_confidence_result_with_valid_responses(self):
        metric = _make_metric()

        # Mock response generation — return 5 distinct answers
        responses = [f"Answer {i}" for i in range(5)]
        with patch.object(metric, "_generate_responses", new_callable=AsyncMock) as mock_gen, \
             patch.object(metric, "_get_embeddings_batch", new_callable=AsyncMock) as mock_emb:
            mock_gen.return_value = responses
            # Return similar embeddings → high confidence
            mock_emb.return_value = [[0.9, 0.1, 0.0]] * 5

            result = await metric._calculate_single("What is X?", "ws1")

        assert isinstance(result, ConfidenceResult)
        assert 0.0 <= result.score <= 1.0
        assert result.num_responses == 5

    @pytest.mark.asyncio
    async def test_returns_default_when_not_enough_responses(self):
        metric = _make_metric()

        with patch.object(metric, "_generate_responses", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = ["Only one"]

            result = await metric._calculate_single("What is X?", "ws1")

        assert isinstance(result, ConfidenceResult)
        assert result.score == 0.5  # default for insufficient responses

    @pytest.mark.asyncio
    async def test_returns_default_on_exception(self):
        metric = _make_metric()

        with patch.object(metric, "_generate_responses", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = RuntimeError("boom")

            result = await metric._calculate_single("What is X?", "ws1")

        assert isinstance(result, ConfidenceResult)
        assert result.score == 0.5


class TestConfidenceFromEmbeddings:
    """Test the static _calculate_confidence_from_embeddings method."""

    def test_identical_embeddings_give_high_confidence(self):
        embeddings = [[1.0, 0.0, 0.0]] * 3
        result = ConfidenceMetric._calculate_confidence_from_embeddings(embeddings)
        assert result["score"] == 1.0

    def test_single_embedding_returns_score_one(self):
        result = ConfidenceMetric._calculate_confidence_from_embeddings([[1.0, 0.0]])
        assert result["score"] == 1.0

    def test_orthogonal_embeddings_give_lower_confidence(self):
        embeddings = [[1.0, 0.0], [0.0, 1.0]]
        result = ConfidenceMetric._calculate_confidence_from_embeddings(embeddings)
        # cosine similarity = 0, normalized = 0.5
        assert result["score"] == pytest.approx(0.5, abs=0.01)
