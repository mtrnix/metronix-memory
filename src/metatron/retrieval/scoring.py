"""Multi-signal scoring for unified reranking.

Combines channel scores (dense, graph, metadata), recency decay,
and source balance into a single normalized signal score. Optionally
blends with cross-encoder rerank score for final ranking.

Default weights (sum = 0.85, output normalized to [0,1]):
- dense:    0.35
- graph:    0.15
- metadata: 0.20
- recency:  0.10
- balance:  0.05
"""

from __future__ import annotations

import math
from datetime import UTC, datetime


def recency_score(
    updated_at: datetime,
    now: datetime | None = None,
    half_life_days: float = 30.0,
) -> float:
    """Exponential time decay — newer documents score higher.

    A document updated half_life_days ago scores 0.5.
    Returns score in (0.0, 1.0].
    """
    if now is None:
        now = datetime.now(UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_days = max((now - updated_at).total_seconds() / 86400.0, 0.0)
    decay_rate = math.log(2) / half_life_days
    return math.exp(-decay_rate * age_days)


def source_balance(
    source_type: str,
    type_counts: dict[str, int],
    total: int,
    threshold: float = 0.4,
) -> float:
    """Return smooth penalty for overrepresented source types.

    Score decays linearly from 1.0 (absent) to 0.0 (at threshold).
    Sources above the threshold get 0.0.
    """
    if total == 0:
        return 1.0
    ratio = type_counts.get(source_type, 0) / total
    if ratio >= threshold:
        return 0.0
    return 1.0 - (ratio / threshold)


def compute_signal_score(
    channel_scores: dict[str, float],
    recency: float = 1.0,
    balance: float = 1.0,
    *,
    dense_weight: float = 0.35,
    graph_weight: float = 0.15,
    metadata_weight: float = 0.20,
    recency_weight: float = 0.10,
    balance_weight: float = 0.05,
    freshness: float = 1.0,
    freshness_weight: float = 0.0,
) -> float:
    """Compute normalized multi-signal score for a retrieval candidate.

    All input scores should be in [0, 1] range.
    Output is normalized by sum of weights to stay in [0, 1].

    Phase B (MTRNIX-313): ``freshness`` carries the ``raw_documents
    .freshness_score`` for the doc that produced this candidate (default
    1.0 when unknown, so scoring behaves identically to Phase A).
    ``freshness_weight`` defaults to 0.0 — when unchanged, the formula is
    numerically identical to Phase A (the term contributes 0 to the
    numerator and 0 to the denominator sum).
    """
    vector = channel_scores.get("dense", 0.0)
    graph = channel_scores.get("graph", 0.0)
    metadata = max(
        channel_scores.get("exact", 0.0),
        channel_scores.get("metadata", 0.0),
    )

    raw = (
        dense_weight * vector
        + graph_weight * graph
        + metadata_weight * metadata
        + recency_weight * recency
        + balance_weight * balance
        + freshness_weight * freshness
    )

    weight_sum = (
        dense_weight
        + graph_weight
        + metadata_weight
        + recency_weight
        + balance_weight
        + freshness_weight
    )
    return raw / weight_sum if weight_sum > 0 else 0.0


def normalize_rerank_scores(results: list[dict]) -> None:
    """Normalize rerank_score values in-place to [0, 1] via min-max.

    If all scores are equal or list has <= 1 element, all scores become 1.0.
    """
    if not results:
        return
    scores = [r.get("rerank_score", 0.0) for r in results]
    min_s = min(scores)
    max_s = max(scores)
    spread = max_s - min_s
    for r in results:
        if spread == 0:
            r["rerank_score"] = 1.0
        else:
            r["rerank_score"] = (r.get("rerank_score", 0.0) - min_s) / spread


def compute_final_score(
    signal_score: float,
    rerank_score: float,
    blend_weight: float = 0.3,
) -> float:
    """Blend multi-signal score with cross-encoder rerank score.

    blend_weight controls the mix: 0.3 means 30% signal + 70% rerank.
    """
    return blend_weight * signal_score + (1 - blend_weight) * rerank_score
