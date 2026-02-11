"""Multi-factor scoring — 6-signal ranking from OpenMemory HSG.

After RRF fusion, each candidate chunk is scored across multiple
dimensions. The final score is a weighted sum used to re-rank results.

Factors and default weights:
- dense:   0.35  (vector similarity from RRF)
- sparse:  0.20  (BM25 keyword match from RRF)
- tag:     0.20  (tag overlap between query and document)
- graph:   0.15  (graph neighborhood relevance)
- recency: 0.10  (time decay — newer documents score higher)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def token_overlap(query_tokens: list[str], chunk_tokens: list[str]) -> float:
    """Compute Jaccard-like token overlap between query and chunk.

    Args:
        query_tokens: Lowercased tokens from the user query.
        chunk_tokens: Lowercased tokens from the chunk content.

    Returns:
        Overlap ratio in [0.0, 1.0].
    """
    if not query_tokens or not chunk_tokens:
        return 0.0
    query_set = set(query_tokens)
    chunk_set = set(chunk_tokens)
    intersection = query_set & chunk_set
    union = query_set | chunk_set
    return len(intersection) / len(union) if union else 0.0


def tag_match(query_tags: list[str], document_tags: list[str]) -> float:
    """Score based on tag overlap between query context and document.

    Args:
        query_tags: Tags extracted from query or user context.
        document_tags: Tags from the document metadata.

    Returns:
        Match ratio in [0.0, 1.0].
    """
    if not query_tags or not document_tags:
        return 0.0
    query_set = {t.lower() for t in query_tags}
    doc_set = {t.lower() for t in document_tags}
    intersection = query_set & doc_set
    return len(intersection) / len(query_set) if query_set else 0.0


def recency_score(
    updated_at: datetime,
    now: datetime | None = None,
    half_life_days: float = 30.0,
) -> float:
    """Exponential time decay — newer documents score higher.

    Uses exponential decay with configurable half-life. A document
    updated half_life_days ago scores 0.5.

    Args:
        updated_at: When the document was last modified.
        now: Current time (defaults to utcnow).
        half_life_days: Days until score decays to 0.5.

    Returns:
        Recency score in (0.0, 1.0].
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


def multi_factor_score(
    rrf_score: float,
    sparse_score: float = 0.0,
    tag_score: float = 0.0,
    graph_score: float = 0.0,
    recency: float = 1.0,
    *,
    dense_weight: float = 0.35,
    sparse_weight: float = 0.20,
    tag_weight: float = 0.20,
    graph_weight: float = 0.15,
    recency_weight: float = 0.10,
) -> float:
    """Compute weighted multi-factor score for a retrieval candidate.

    Combines six scoring signals into a single ranking score.
    All input scores should be in [0, 1] range.

    Args:
        rrf_score: RRF fusion score (normalized to [0, 1]).
        sparse_score: Sparse/BM25 relevance score.
        tag_score: Tag overlap score from tag_match().
        graph_score: Graph neighborhood relevance score.
        recency: Time decay score from recency_score().
        dense_weight: Weight for RRF/dense signal.
        sparse_weight: Weight for sparse/BM25 signal.
        tag_weight: Weight for tag matching.
        graph_weight: Weight for graph enrichment.
        recency_weight: Weight for recency.

    Returns:
        Weighted sum score. Higher is better.
    """
    return (
        dense_weight * rrf_score
        + sparse_weight * sparse_score
        + tag_weight * tag_score
        + graph_weight * graph_score
        + recency_weight * recency
    )
