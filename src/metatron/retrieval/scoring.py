"""Multi-signal scoring for unified reranking.

Combines channel scores (dense, sparse, graph, metadata), recency decay,
and source balance into a single normalized signal score. Optionally
blends with cross-encoder rerank score for final ranking.

Default weights (sum = 0.85, output normalized to [0,1]):
- dense:    0.35
- sparse:   0.00  (placeholder — RRF doesn't separate dense/sparse)
- graph:    0.15
- metadata: 0.20
- recency:  0.10
- balance:  0.05
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


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
        now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_days = max((now - updated_at).total_seconds() / 86400.0, 0.0)
    decay_rate = math.log(2) / half_life_days
    return math.exp(-decay_rate * age_days)


def source_balance(
    source_type: str,
    type_counts: dict[str, int],
    total: int,
    threshold: float = 0.4,
) -> float:
    """Return 1.0 if source type is underrepresented, 0.0 if overrepresented.

    A source type is overrepresented if it makes up > threshold of the pool.
    """
    if total == 0:
        return 1.0
    count = type_counts.get(source_type, 0)
    return 0.0 if count / total > threshold else 1.0


def compute_signal_score(
    channel_scores: dict[str, float],
    recency: float = 1.0,
    balance: float = 1.0,
    *,
    dense_weight: float = 0.35,
    sparse_weight: float = 0.0,
    graph_weight: float = 0.15,
    metadata_weight: float = 0.20,
    recency_weight: float = 0.10,
    balance_weight: float = 0.05,
) -> float:
    """Compute normalized multi-signal score for a retrieval candidate.

    All input scores should be in [0, 1] range.
    Output is normalized by sum of weights to stay in [0, 1].
    """
    vector = channel_scores.get("dense", 0.0)
    sparse = channel_scores.get("sparse", 0.0)
    graph = channel_scores.get("graph", 0.0)
    metadata = max(
        channel_scores.get("exact", 0.0),
        channel_scores.get("metadata", 0.0),
    )

    raw = (
        dense_weight * vector
        + sparse_weight * sparse
        + graph_weight * graph
        + metadata_weight * metadata
        + recency_weight * recency
        + balance_weight * balance
    )

    weight_sum = (
        dense_weight + sparse_weight + graph_weight
        + metadata_weight + recency_weight + balance_weight
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
