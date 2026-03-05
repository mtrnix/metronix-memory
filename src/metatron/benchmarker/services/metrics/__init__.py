"""
Metrics package — 6 quality metrics for RAG system evaluation.

Provides:
- ConfidenceMetric: stub (always 1.0)
- QEDMetricsCalculator: correctness via BenchmarkQED AutoE
- AnswerRelevancyMetric: cosine similarity of embeddings
- FaithfulnessMetric: LLM-as-Judge faithfulness
- ContextPrecisionMetric: LLM-as-Judge context precision
- ContextRecallMetric: LLM-as-Judge context recall
- MetricsController: orchestrator for parallel computation of all 6 metrics
"""

from metatron.benchmarker.services.metrics.confidence import ConfidenceMetric
from metatron.benchmarker.services.metrics.context_precision import (
    ContextPrecisionMetric,
    ContextPrecisionResult,
)
from metatron.benchmarker.services.metrics.context_recall import (
    ContextRecallMetric,
    ContextRecallResult,
)
from metatron.benchmarker.services.metrics.controller import MetricsController
from metatron.benchmarker.services.metrics.faithfulness import (
    FaithfulnessMetric,
    FaithfulnessResult,
)
from metatron.benchmarker.services.metrics.qed import QEDMetricsCalculator
from metatron.benchmarker.services.metrics.relevancy import (
    AnswerRelevancyMetric,
    RelevancyResult,
)

__all__ = [
    "ConfidenceMetric",
    "QEDMetricsCalculator",
    "AnswerRelevancyMetric",
    "RelevancyResult",
    "FaithfulnessMetric",
    "FaithfulnessResult",
    "ContextPrecisionMetric",
    "ContextPrecisionResult",
    "ContextRecallMetric",
    "ContextRecallResult",
    "MetricsController",
]
