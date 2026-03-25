"""Deterministic retrieval metrics: Precision@K, MRR, NDCG@K.

These metrics compare retrieved doc_labels against ground-truth
expected doc_labels. No LLM calls — pure math.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def precision_at_k(retrieved: Sequence[str], expected: set[str], k: int) -> float:
    """Precision@K: fraction of top-K retrieved that are relevant.

    Uses min(k, len(retrieved)) as denominator when fewer than K docs retrieved.
    Returns 0.0 if retrieved or expected is empty.
    """
    if not retrieved or not expected:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    relevant = sum(1 for doc in top_k if doc in expected)
    return relevant / len(top_k)


def mean_reciprocal_rank(retrieved: Sequence[str], expected: set[str]) -> float:
    """MRR: 1/rank of first relevant doc. 0 if none found."""
    if not retrieved or not expected:
        return 0.0
    for i, doc in enumerate(retrieved, start=1):
        if doc in expected:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], expected: set[str], k: int = 10) -> float:
    """NDCG@K with binary relevance.

    DCG  = sum(rel_i / log2(i + 1)) for i in 1..k  (1-indexed)
    IDCG = DCG of ideal ranking (all relevant docs first)
    NDCG = DCG / IDCG
    """
    if not retrieved or not expected:
        return 0.0
    top_k = retrieved[:k]

    # DCG: sum of 1/log2(i+1) for each relevant doc at position i (1-indexed)
    dcg = 0.0
    for i, doc in enumerate(top_k):
        if doc in expected:
            dcg += 1.0 / math.log2(i + 2)  # i+2 because i is 0-indexed, formula uses 1-indexed +1

    if dcg == 0.0:
        return 0.0

    # IDCG: best possible DCG with min(|expected|, k) relevant docs at top
    num_relevant = min(len(expected), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(num_relevant))

    return dcg / idcg


class RetrievalMetrics:
    """Convenience class to compute all 3 retrieval metrics together."""

    def compute(
        self,
        retrieved: Sequence[str],
        expected: set[str],
        k: int = 10,
    ) -> dict[str, float]:
        """Compute all retrieval metrics for a single query."""
        return {
            "precision_at_k": precision_at_k(retrieved, expected, k),
            "mrr": mean_reciprocal_rank(retrieved, expected),
            "ndcg_at_k": ndcg_at_k(retrieved, expected, k),
            "k": float(k),
        }

    def compute_batch(
        self,
        pairs: Sequence[tuple[Sequence[str], set[str]]],
        k: int = 10,
    ) -> list[dict[str, float]]:
        """Compute metrics for multiple (retrieved, expected) pairs."""
        return [self.compute(retrieved, expected, k) for retrieved, expected in pairs]

    def compute_averages(
        self,
        pairs: Sequence[tuple[Sequence[str], set[str]]],
        k: int = 10,
    ) -> dict[str, float]:
        """Compute averaged metrics across all pairs."""
        if not pairs:
            return {
                "avg_precision_at_k": 0.0,
                "avg_mrr": 0.0,
                "avg_ndcg_at_k": 0.0,
            }
        results = self.compute_batch(pairs, k)
        n = len(results)
        return {
            "avg_precision_at_k": sum(r["precision_at_k"] for r in results) / n,
            "avg_mrr": sum(r["mrr"] for r in results) / n,
            "avg_ndcg_at_k": sum(r["ndcg_at_k"] for r in results) / n,
        }
