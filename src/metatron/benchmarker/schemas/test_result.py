"""
Test result schemas — metric results for a single test question.

Adapted from metatron-benchmarker for integration into Metatron Core.
MetricsResult holds the values of all 6 metrics computed by MetricsController.
ConfidenceResult is a lightweight container for the Confidence metric
(currently a stub returning score=1.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfidenceResult:
    """Result of the Confidence metric evaluation."""

    score: float = 0.0
    avg_similarity: float = 0.0
    min_similarity: float | None = None
    max_similarity: float | None = None
    num_responses: int = 0


@dataclass
class MetricsResult:
    """Results of all 6 metrics for one test question."""

    # Black-box metrics
    correctness: float | None = None  # 0-100 (percentage)
    answer_relevancy: float | None = None  # 0-1

    # White-box metrics (LLM-as-Judge)
    faithfulness: float | None = None  # 0-1
    context_precision: float | None = None  # 0-1
    context_recall: float | None = None  # 0-1

    # Confidence metric (stub: always 1.0)
    confidence: float | None = None  # 0-1

    # Retrieval metrics (deterministic, doc_label based)
    ndcg_at_10: float | None = None  # 0-1
    mrr: float | None = None  # 0-1
    precision_at_k: float | None = None  # 0-1

    # Detail data for Correctness
    claim_scores: list[dict] | None = field(default=None)

    # Detail data for Context Precision
    chunk_scores: list[float] | None = field(default=None)

    # Reasoning strings from LLM-as-Judge metrics
    faithfulness_reasoning: str | None = None
    recall_reasoning: str | None = None
