"""
Test result schemas — metric results for a single test question.

Adapted from metatron-benchmarker for integration into Metatron Core.
MetricsResult holds the values of all 6 metrics computed by MetricsController.
ConfidenceResult is a lightweight container for the Confidence metric
(currently a stub returning score=1.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ConfidenceResult:
    """Result of the Confidence metric evaluation."""

    score: float = 0.0
    avg_similarity: float = 0.0
    min_similarity: Optional[float] = None
    max_similarity: Optional[float] = None
    num_responses: int = 0


@dataclass
class MetricsResult:
    """Results of all 6 metrics for one test question."""

    # Black-box metrics
    correctness: Optional[float] = None       # 0-100 (percentage)
    answer_relevancy: Optional[float] = None   # 0-1

    # White-box metrics (LLM-as-Judge)
    faithfulness: Optional[float] = None       # 0-1
    context_precision: Optional[float] = None  # 0-1
    context_recall: Optional[float] = None     # 0-1

    # Confidence metric (stub: always 1.0)
    confidence: Optional[float] = None         # 0-1

    # Retrieval metrics (deterministic, doc_label based)
    ndcg_at_10: Optional[float] = None       # 0-1
    mrr: Optional[float] = None              # 0-1
    precision_at_k: Optional[float] = None   # 0-1

    # Detail data for Correctness
    claim_scores: Optional[List[Dict]] = field(default=None)

    # Detail data for Context Precision
    chunk_scores: Optional[List[float]] = field(default=None)

    # Reasoning strings from LLM-as-Judge metrics
    faithfulness_reasoning: Optional[str] = None
    recall_reasoning: Optional[str] = None
