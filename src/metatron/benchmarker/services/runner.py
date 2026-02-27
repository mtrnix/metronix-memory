"""
Test Runner — orchestrate testing: questions → RAG → metrics.

For each question in a benchmark set, the runner calls
``hybrid_search_and_answer(return_trace=True)`` to get the RAG answer
and white-box retrieval data, measures latency, builds a TestContext,
and fetches full chunk data via ContextFetcher.  After all questions
are processed, MetricsController computes the 6 metrics in parallel.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List

from metatron.benchmarker.schemas.benchmark import BenchmarkQuestion
from metatron.benchmarker.schemas.test_context import TestContext
from metatron.benchmarker.schemas.test_result import MetricsResult
from metatron.retrieval.search import hybrid_search_and_answer

if TYPE_CHECKING:
    from metatron.benchmarker.services.context_fetcher import ContextFetcher

logger = logging.getLogger(__name__)


class TestRunner:
    """Orchestrate testing: questions → RAG → metrics."""

    def __init__(
        self,
        metrics_controller: Any,
        context_fetcher: "ContextFetcher",
    ) -> None:
        self.metrics = metrics_controller
        self.ctx_fetcher = context_fetcher

    async def run_tests(
        self,
        questions: List[BenchmarkQuestion],
        workspace_id: str,
    ) -> Dict[str, Any]:
        """
        Run all benchmark questions through the RAG pipeline and compute metrics.

        For each question:
        1. Call ``hybrid_search_and_answer(query, workspace_id, return_trace=True)``
        2. Measure latency (wall-clock time before and after the call)
        3. Build a :class:`TestContext` with the answer, latency, and white-box data
        4. Fetch full chunk data via :class:`ContextFetcher`

        Then:
        5. Pass all contexts to ``MetricsController.calculate_all()``
        6. Compute average metrics via ``compute_avg_metrics``
        7. Return a dict with questions, contexts, metrics_results, and avg_metrics
        """
        contexts: List[TestContext] = []

        for q in questions:
            ctx = await self._run_single(q, workspace_id)
            contexts.append(ctx)

        # Compute metrics for all contexts
        metrics_results = await self._calculate_metrics(contexts)

        # Compute average metrics from results
        avg_metrics = self._compute_avg_metrics(metrics_results)

        return {
            "questions": questions,
            "contexts": contexts,
            "metrics_results": metrics_results,
            "avg_metrics": avg_metrics,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_single(
        self,
        question: BenchmarkQuestion,
        workspace_id: str,
    ) -> TestContext:
        """Run a single question through the RAG pipeline and build a TestContext."""
        start = time.time()
        try:
            trace = hybrid_search_and_answer(
                query=question.text,
                workspace_id=workspace_id,
                return_trace=True,
            )
            latency_ms = (time.time() - start) * 1000

            answer = trace["answer"] if isinstance(trace, dict) else str(trace)
            source_results = trace.get("source_results", []) if isinstance(trace, dict) else []
            fragments = trace.get("fragments", []) if isinstance(trace, dict) else []
            graph_entities = trace.get("graph_entities", []) if isinstance(trace, dict) else []

        except Exception as exc:
            latency_ms = (time.time() - start) * 1000
            logger.error(
                "hybrid_search_and_answer failed for question '%s': %s",
                question.id,
                exc,
            )
            answer = f"ERROR: {exc}"
            source_results = []
            fragments = []
            graph_entities = []

        ctx = TestContext(
            question=question,
            answer=answer,
            latency_ms=latency_ms,
            workspace_id=workspace_id,
            source_results=source_results,
            fragments=fragments,
            graph_entities=graph_entities,
        )

        # Fetch full chunk data from Qdrant
        if source_results:
            try:
                chunks = await self.ctx_fetcher.fetch_chunks(source_results)
                ctx.source_chunks = chunks
            except Exception as exc:
                logger.warning(
                    "ContextFetcher failed for question '%s': %s",
                    question.id,
                    exc,
                )

        return ctx

    async def _calculate_metrics(
        self,
        contexts: List[TestContext],
    ) -> List[MetricsResult]:
        """Calculate metrics for all contexts, returning empty results on failure."""
        try:
            return await self.metrics.calculate_all(contexts)
        except Exception as exc:
            logger.error("MetricsController.calculate_all failed: %s", exc)
            return [MetricsResult() for _ in contexts]

    @staticmethod
    def _compute_avg_metrics(
        results: List[MetricsResult],
    ) -> Dict[str, float | None]:
        """Compute average of non-None values for each of the 6 metrics."""
        metric_names = (
            "correctness",
            "answer_relevancy",
            "faithfulness",
            "context_precision",
            "context_recall",
            "confidence",
        )
        avg: Dict[str, float | None] = {}
        for metric in metric_names:
            values = [
                getattr(r, metric)
                for r in results
                if getattr(r, metric) is not None
            ]
            avg[f"avg_{metric}"] = sum(values) / len(values) if values else None
        return avg

    def __str__(self) -> str:
        return f"TestRunner(metrics={self.metrics}, ctx_fetcher={self.ctx_fetcher})"

    def __repr__(self) -> str:
        return (
            f"TestRunner("
            f"metrics_controller={self.metrics!r}, "
            f"context_fetcher={self.ctx_fetcher!r}"
            f")"
        )
