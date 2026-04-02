"""Tests for TestRunner — orchestration of RAG testing and metrics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.benchmarker.schemas.benchmark import (
    BenchmarkQuestion,
    Claim,
    QuestionAttributes,
)
from metatron.benchmarker.schemas.test_context import ChunkData
from metatron.benchmarker.schemas.test_result import MetricsResult
from metatron.benchmarker.services.runner import TestRunner


@pytest.fixture
def mock_metrics_controller():
    """Mock MetricsController."""
    controller = MagicMock()
    controller.calculate_all = AsyncMock(
        return_value=[
            MetricsResult(
                correctness=0.8,
                answer_relevancy=0.9,
                faithfulness=0.85,
                context_precision=0.75,
                context_recall=0.7,
                confidence=0.95,
            )
        ]
    )
    return controller


@pytest.fixture
def mock_context_fetcher():
    """Mock ContextFetcher."""
    fetcher = MagicMock()
    fetcher.fetch_chunks = AsyncMock(
        return_value=[
            ChunkData(
                id="chunk1",
                title="Test Doc",
                data="Test content",
                doc_label="doc1",
                score=0.9,
            )
        ]
    )
    return fetcher


@pytest.fixture
def sample_question():
    """Sample benchmark question."""
    return BenchmarkQuestion(
        id="q1",
        text="What is the capital of France?",
        question_type="data_local",
        references=["ref1"],
        attributes=QuestionAttributes(
            input_question="What is the capital of France?",
            reference_coverage=0.9,
            relevant_reference_count=1,
            reference_count=1,
            min_reference_similarity=0.8,
            max_reference_similarity=0.95,
            mean_reference_similarity=0.9,
            intra_inter_similarity_ratio=0.85,
            claim_count=1,
            claims=[
                Claim(
                    statement="Paris is the capital of France",
                    sources=[],
                    score=1.0,
                    source_ids=["ref1"],
                )
            ],
        ),
    )


class TestRunnerInitialization:
    """Test TestRunner initialization."""

    def test_init(self, mock_metrics_controller, mock_context_fetcher):
        """Test runner initialization."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)
        assert runner.metrics == mock_metrics_controller
        assert runner.ctx_fetcher == mock_context_fetcher


class TestRunSingle:
    """Test _run_single method."""

    @pytest.mark.asyncio
    async def test_run_single_success(
        self, mock_metrics_controller, mock_context_fetcher, sample_question
    ):
        """Test successful single question execution."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)

        mock_trace = {
            "answer": "Paris is the capital of France.",
            "source_results": [{"id": "chunk1", "score": 0.9}],
            "fragments": ["Paris is the capital"],
            "graph_entities": [],
        }

        with patch(
            "metatron.benchmarker.services.runner.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=mock_trace,
        ):
            ctx = await runner._run_single(sample_question, "workspace1")

        assert ctx.question == sample_question
        assert ctx.answer == "Paris is the capital of France."
        assert ctx.workspace_id == "workspace1"
        assert ctx.latency_ms > 0
        assert len(ctx.source_results) == 1
        assert len(ctx.source_chunks) == 1

    @pytest.mark.asyncio
    async def test_run_single_error_handling(
        self, mock_metrics_controller, mock_context_fetcher, sample_question
    ):
        """Test error handling in single question execution."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)

        with patch(
            "metatron.benchmarker.services.runner.hybrid_search_and_answer",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RAG failed"),
        ):
            ctx = await runner._run_single(sample_question, "workspace1")

        assert ctx.question == sample_question
        assert "ERROR: RAG failed" in ctx.answer
        assert ctx.latency_ms > 0
        assert len(ctx.source_results) == 0

    @pytest.mark.asyncio
    async def test_run_single_context_fetcher_failure(
        self, mock_metrics_controller, mock_context_fetcher, sample_question
    ):
        """Test handling of context fetcher failure."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)
        mock_context_fetcher.fetch_chunks.side_effect = RuntimeError("Qdrant down")

        mock_trace = {
            "answer": "Paris",
            "source_results": [{"id": "chunk1"}],
            "fragments": [],
            "graph_entities": [],
        }

        with patch(
            "metatron.benchmarker.services.runner.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=mock_trace,
        ):
            ctx = await runner._run_single(sample_question, "workspace1")

        # Should continue despite fetcher failure
        assert ctx.answer == "Paris"
        # source_chunks remains None when fetcher fails
        assert ctx.source_chunks is None or len(ctx.source_chunks) == 0


class TestRunTests:
    """Test run_tests method."""

    @pytest.mark.asyncio
    async def test_run_tests_success(
        self, mock_metrics_controller, mock_context_fetcher, sample_question
    ):
        """Test successful test run with multiple questions."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)

        questions = [sample_question]
        mock_trace = {
            "answer": "Paris",
            "source_results": [{"id": "chunk1", "score": 0.9}],
            "fragments": ["Paris is the capital"],
            "graph_entities": [],
        }

        with patch(
            "metatron.benchmarker.services.runner.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=mock_trace,
        ):
            result = await runner.run_tests(questions, "workspace1")

        assert "questions" in result
        assert "contexts" in result
        assert "metrics_results" in result
        assert "avg_metrics" in result

        assert len(result["questions"]) == 1
        assert len(result["contexts"]) == 1
        assert len(result["metrics_results"]) == 1

        # Check average metrics
        avg = result["avg_metrics"]
        assert "avg_correctness" in avg
        assert "avg_answer_relevancy" in avg
        assert avg["avg_correctness"] == 0.8

    @pytest.mark.asyncio
    async def test_run_tests_metrics_failure(
        self, mock_metrics_controller, mock_context_fetcher, sample_question
    ):
        """Test handling of metrics calculation failure."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)
        mock_metrics_controller.calculate_all.side_effect = RuntimeError("Metrics failed")

        questions = [sample_question]
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
            result = await runner.run_tests(questions, "workspace1")

        # Should return empty metrics results
        assert len(result["metrics_results"]) == 1
        assert result["metrics_results"][0].correctness is None


class TestComputeAvgMetrics:
    """Test _compute_avg_metrics static method."""

    def test_compute_avg_metrics_all_values(self):
        """Test average computation with all values present."""
        results = [
            MetricsResult(
                correctness=0.8,
                answer_relevancy=0.9,
                faithfulness=0.85,
                context_precision=0.75,
                context_recall=0.7,
                confidence=0.95,
            ),
            MetricsResult(
                correctness=0.6,
                answer_relevancy=0.7,
                faithfulness=0.65,
                context_precision=0.55,
                context_recall=0.5,
                confidence=0.75,
            ),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        assert avg["avg_correctness"] == 0.7
        assert avg["avg_answer_relevancy"] == 0.8
        assert avg["avg_faithfulness"] == 0.75

    def test_compute_avg_metrics_with_none_values(self):
        """Test average computation with some None values."""
        results = [
            MetricsResult(correctness=0.8, answer_relevancy=None),
            MetricsResult(correctness=0.6, answer_relevancy=0.7),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        assert avg["avg_correctness"] == 0.7
        assert avg["avg_answer_relevancy"] == 0.7

    def test_compute_avg_metrics_all_none(self):
        """Test average computation when all values are None."""
        results = [
            MetricsResult(correctness=None),
            MetricsResult(correctness=None),
        ]

        avg = TestRunner._compute_avg_metrics(results)

        assert avg["avg_correctness"] is None


class TestRunnerStringRepresentation:
    """Test string representations."""

    def test_str(self, mock_metrics_controller, mock_context_fetcher):
        """Test __str__ method."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)
        result = str(runner)
        assert "TestRunner" in result
        assert "metrics=" in result

    def test_repr(self, mock_metrics_controller, mock_context_fetcher):
        """Test __repr__ method."""
        runner = TestRunner(mock_metrics_controller, mock_context_fetcher)
        result = repr(runner)
        assert "TestRunner" in result
        assert "metrics_controller=" in result
