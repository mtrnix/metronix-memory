"""Reciprocal Rank Fusion (RRF) — merges dense + sparse search results.

RRF combines ranked lists without requiring score normalization.
Formula: score(d) = sum(1 / (k + rank_i(d))) for each list i.

UNION merge: a document appears in the final list if it appears in
ANY of the input lists (not required to be in all of them).
"""

from __future__ import annotations


def rrf_fusion(
    *ranked_lists: list[tuple[str, float]],
    k: int = 60,
    top_k: int = 20,
) -> list[tuple[str, float]]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Each input list contains (doc_id, score) tuples sorted by descending
    score. The original scores are ignored — only rank positions matter.

    Uses UNION merge: a document scores 0 for lists it doesn't appear in.

    Args:
        *ranked_lists: Variable number of ranked result lists.
            Each is a list of (chunk_id, score) tuples.
        k: RRF smoothing constant. Higher k reduces the influence
           of high-ranking items. Standard value: 60.
        top_k: Number of results to return.

    Returns:
        Merged list of (chunk_id, rrf_score) tuples, sorted descending.

    Example:
        dense = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        sparse = [("b", 5.0), ("d", 4.0), ("a", 3.0)]
        merged = rrf_fusion(dense, sparse, k=60)
        # "b" ranks high in both → highest RRF score
    """
    if not ranked_lists:
        return []

    scores: dict[str, float] = {}

    for ranked_list in ranked_lists:
        for rank, (doc_id, _original_score) in enumerate(ranked_list):
            rrf_score = 1.0 / (k + rank + 1)
            scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score

    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:top_k]
