"""
Metrics Controller — orchestrate parallel computation of all 6 metrics.

Coordinates the execution of Correctness (QED AutoE), Answer Relevancy,
Faithfulness, Context Precision, Context Recall, and Confidence metrics.
Uses ``asyncio.gather()`` for parallel computation.  White-box metrics
(faithfulness, precision, recall) are only computed for contexts that
have white-box data available.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from metatron.benchmarker.schemas.test_context import TestContext
from metatron.benchmarker.schemas.test_result import MetricsResult
from metatron.benchmarker.services.metrics.confidence import ConfidenceMetric
from metatron.benchmarker.services.metrics.context_precision import (
    ContextPrecisionMetric,
)
from metatron.benchmarker.services.metrics.context_recall import (
    ContextRecallMetric,
)
from metatron.benchmarker.services.metrics.faithfulness import (
    FaithfulnessMetric,
)
from metatron.benchmarker.services.metrics.qed import QEDMetricsCalculator
from metatron.benchmarker.services.metrics.relevancy import (
    AnswerRelevancyMetric,
)
from metatron.benchmarker.services.metrics.retrieval import RetrievalMetrics

if TYPE_CHECKING:
    from metatron.core.config import Settings

logger = structlog.get_logger()


class MetricsController:
    """Orchestrate parallel computation of all 6 metrics.

    Uses ``asyncio.gather()`` to run all metric calculations concurrently.
    White-box metrics (faithfulness, context precision, context recall) are
    only computed for contexts where ``has_white_box_data`` is True.
    On error in any individual metric, that metric returns None and the
    remaining metrics continue.
    """

    def __init__(
        self,
        deepseek_api_key: str,
        embedding_base_url: str = "http://localhost:8001",
        deepseek_model: str = "deepseek-chat",
        embedding_model: str = "nomic-embed-text",
    ) -> None:
        self.qed = QEDMetricsCalculator(
            deepseek_api_key=deepseek_api_key,
            deepseek_model=deepseek_model,
        )
        self.relevancy = AnswerRelevancyMetric(
            embedding_base_url=embedding_base_url,
            embedding_model=embedding_model,
        )
        self.faithfulness = FaithfulnessMetric(
            deepseek_api_key=deepseek_api_key,
            deepseek_model=deepseek_model,
        )
        self.precision = ContextPrecisionMetric(
            deepseek_api_key=deepseek_api_key,
            deepseek_model=deepseek_model,
        )
        self.recall = ContextRecallMetric(
            deepseek_api_key=deepseek_api_key,
            deepseek_model=deepseek_model,
        )
        self.confidence = ConfidenceMetric(
            embedding_base_url=embedding_base_url,
            embedding_model=embedding_model,
        )
        self.retrieval = RetrievalMetrics()

        logger.info(
            "MetricsController initialized: model=%s, embedding_url=%s",
            deepseek_model,
            embedding_base_url,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> MetricsController:
        """Create a MetricsController from Metatron Core settings.

        Maps ``Settings`` fields to constructor arguments:
        * ``deepseek_api_key`` from ``settings.deepseek_api_key``
        * ``embedding_base_url`` from ``settings.benchmarker_embedding_proxy_url``
        * ``deepseek_model`` from ``settings.deepseek_model``
        * ``embedding_model`` from ``settings.ollama_embed_model``
        """
        return cls(
            deepseek_api_key=settings.deepseek_api_key,
            embedding_base_url=settings.benchmarker_embedding_proxy_url,
            deepseek_model=settings.deepseek_model,
            embedding_model=settings.ollama_embed_model,
        )

    async def calculate_all(
        self,
        contexts: list[TestContext],
    ) -> list[MetricsResult]:
        """Compute all 6 metrics for a list of test contexts in parallel.

        Uses ``asyncio.gather()`` to run correctness, relevancy, faithfulness,
        context precision, context recall, and confidence concurrently.

        Args:
            contexts: List of :class:`TestContext` with question, answer,
                and optional white-box data.

        Returns:
            List of :class:`MetricsResult`, one per context.
        """
        if not contexts:
            return []

        # Run all 7 metrics in parallel
        (
            correctness_results,
            relevancy_results,
            faithfulness_results,
            precision_results,
            recall_results,
            confidence_results,
            retrieval_results,
        ) = await asyncio.gather(
            self._calc_correctness(contexts),
            self._calc_relevancy(contexts),
            self._calc_faithfulness(contexts),
            self._calc_precision(contexts),
            self._calc_recall(contexts),
            self._calc_confidence(contexts),
            self._calc_retrieval(contexts),
        )

        # Merge results into MetricsResult objects
        results: list[MetricsResult] = []
        for i in range(len(contexts)):
            result = MetricsResult(
                correctness=self._safe_get(correctness_results, i, "score"),
                answer_relevancy=self._safe_get(relevancy_results, i, "score"),
                faithfulness=self._safe_get(faithfulness_results, i, "score"),
                context_precision=self._safe_get(precision_results, i, "score"),
                context_recall=self._safe_get(recall_results, i, "score"),
                confidence=self._safe_get(confidence_results, i, "score"),
                claim_scores=self._safe_get(correctness_results, i, "claim_scores"),
                chunk_scores=self._safe_get(precision_results, i, "chunk_scores"),
                faithfulness_reasoning=self._safe_get(
                    faithfulness_results,
                    i,
                    "reasoning",
                ),
                recall_reasoning=self._safe_get(
                    recall_results,
                    i,
                    "reasoning",
                ),
                ndcg_at_10=self._safe_get(retrieval_results, i, "ndcg_at_k"),
                mrr=self._safe_get(retrieval_results, i, "mrr"),
                precision_at_k=self._safe_get(retrieval_results, i, "precision_at_k"),
            )
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Individual metric calculators (with error handling)
    # ------------------------------------------------------------------

    async def _calc_correctness(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate correctness via QED AutoE."""
        try:
            questions = [ctx.question for ctx in contexts]
            answers = [ctx.answer for ctx in contexts]
            latencies = [ctx.latency_ms for ctx in contexts]

            results = await self.qed.evaluate_answers(questions, answers, latencies)
            return results
        except Exception as exc:
            logger.error("Correctness metric failed: %s", exc)
            return None

    async def _calc_relevancy(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate answer relevancy via embedding cosine similarity."""
        try:
            questions = [ctx.question.text for ctx in contexts]
            answers = [ctx.answer for ctx in contexts]
            results = await self.relevancy.calculate_batch(questions, answers)
            return results
        except Exception as exc:
            logger.error("Relevancy metric failed: %s", exc)
            return None

    async def _calc_faithfulness(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate faithfulness for contexts with white-box data."""
        try:
            questions: list[str] = []
            answers: list[str] = []
            context_texts: list[str] = []
            wb_indices: list[int] = []

            for i, ctx in enumerate(contexts):
                if ctx.has_white_box_data:
                    questions.append(ctx.question.text)
                    answers.append(ctx.answer)
                    context_texts.append(ctx.context_text)
                    wb_indices.append(i)

            if not questions:
                return None

            wb_results = await self.faithfulness.calculate_batch(
                questions,
                answers,
                context_texts,
            )

            # Map results back to full context list
            full_results: list = [None] * len(contexts)
            for idx, wb_idx in enumerate(wb_indices):
                full_results[wb_idx] = wb_results[idx]

            return full_results
        except Exception as exc:
            logger.error("Faithfulness metric failed: %s", exc)
            return None

    async def _calc_precision(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate context precision for contexts with white-box data."""
        try:
            questions: list[str] = []
            chunks_per_question: list[list[str]] = []
            wb_indices: list[int] = []

            for i, ctx in enumerate(contexts):
                if ctx.has_white_box_data:
                    questions.append(ctx.question.text)
                    chunk_texts = [c.data for c in ctx.all_chunks] if ctx.all_chunks else []
                    chunks_per_question.append(chunk_texts)
                    wb_indices.append(i)

            if not questions:
                return None

            wb_results = await self.precision.calculate_batch(
                questions,
                chunks_per_question,
            )

            # Map results back to full context list
            full_results: list = [None] * len(contexts)
            for idx, wb_idx in enumerate(wb_indices):
                full_results[wb_idx] = wb_results[idx]

            return full_results
        except Exception as exc:
            logger.error("Context precision metric failed: %s", exc)
            return None

    async def _calc_recall(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate context recall for contexts with white-box data."""
        try:
            questions: list[str] = []
            answers: list[str] = []
            context_texts: list[str] = []
            ground_truths: list[str] = []
            wb_indices: list[int] = []

            for i, ctx in enumerate(contexts):
                if ctx.has_white_box_data:
                    questions.append(ctx.question.text)
                    answers.append(ctx.answer)
                    context_texts.append(ctx.context_text)
                    # Build ground truth from claims
                    claims = ctx.question.attributes.claims
                    gt = " ".join(c.statement for c in claims) if claims else ""
                    ground_truths.append(gt)
                    wb_indices.append(i)

            if not questions:
                return None

            wb_results = await self.recall.calculate_batch(
                questions,
                answers,
                context_texts,
                ground_truths,
            )

            # Map results back to full context list
            full_results: list = [None] * len(contexts)
            for idx, wb_idx in enumerate(wb_indices):
                full_results[wb_idx] = wb_results[idx]

            return full_results
        except Exception as exc:
            logger.error("Context recall metric failed: %s", exc)
            return None

    async def _calc_retrieval(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate retrieval metrics for contexts with expected labels."""
        try:
            results = []
            for ctx in contexts:
                if ctx.expected_doc_labels and ctx.retrieved_doc_labels:
                    r = self.retrieval.compute(
                        ctx.retrieved_doc_labels,
                        ctx.expected_doc_labels,
                        k=10,
                    )
                    results.append(r)
                else:
                    results.append(None)
            return results
        except Exception as exc:
            logger.error("Retrieval metrics failed: %s", exc)
            return None

    async def _calc_confidence(
        self,
        contexts: list[TestContext],
    ) -> list | None:
        """Calculate confidence via response consistency."""
        try:
            questions = [ctx.question.text for ctx in contexts]
            workspace_id = contexts[0].workspace_id if contexts else None
            results = await self.confidence.calculate_batch(
                questions,
                workspace_id=workspace_id,
            )
            return results
        except Exception as exc:
            logger.error("Confidence metric failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_get(results: list | None, index: int, attr: str):
        """Safely extract an attribute from a result at the given index.

        Returns None if results is None, index is out of range,
        or the result at that index is None.
        """
        if results is None or index >= len(results):
            return None

        item = results[index]
        if item is None:
            return None

        if isinstance(item, dict):
            return item.get(attr)

        return getattr(item, attr, None)

    def __str__(self) -> str:
        return "MetricsController(6 metrics)"

    def __repr__(self) -> str:
        return (
            f"MetricsController("
            f"qed={self.qed!r}, "
            f"relevancy={self.relevancy!r}, "
            f"faithfulness={self.faithfulness!r}, "
            f"precision={self.precision!r}, "
            f"recall={self.recall!r}, "
            f"confidence={self.confidence!r}"
            f")"
        )
