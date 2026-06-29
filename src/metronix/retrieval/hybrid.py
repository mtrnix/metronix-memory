"""Reciprocal Rank Fusion (RRF) — merges dense + sparse search results.

RRF combines ranked lists without requiring score normalization.
Formula: score(d) = sum(1 / (k + rank_i(d))) for each list i.

UNION merge: a document appears in the final list if it appears in
ANY of the input lists (not required to be in all of them).
"""

from __future__ import annotations


def compute_jaccard_overlap(
    list_a: list[tuple[str, float]],
    list_b: list[tuple[str, float]],
) -> float:
    """Compute Jaccard similarity on the ID sets of two ranked lists.

    Args:
        list_a: List of (id, score) tuples.
        list_b: List of (id, score) tuples.

    Returns:
        Jaccard similarity: |A ∩ B| / |A ∪ B|. Returns 0.0 if both empty.
    """
    ids_a = {doc_id for doc_id, _ in list_a}
    ids_b = {doc_id for doc_id, _ in list_b}
    union = ids_a | ids_b
    if not union:
        return 0.0
    return len(ids_a & ids_b) / len(union)


def compute_adaptive_k(
    overlap: float,
    k_low: int,
    k_high: int,
    threshold_low: float,
    threshold_high: float,
) -> int:
    """Compute adaptive RRF k based on dense/sparse overlap.

    High overlap (>= threshold_high) → k_low (trust rankings).
    Low overlap (<= threshold_low) → k_high (flatten scores).
    Between: linear interpolation.

    Returns:
        Integer k value between k_low and k_high.
    """
    if overlap >= threshold_high:
        return k_low
    if overlap <= threshold_low:
        return k_high
    # Linear interpolation: as overlap increases from low→high, k decreases from high→low
    ratio = (overlap - threshold_low) / (threshold_high - threshold_low)
    return round(k_high + ratio * (k_low - k_high))


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
