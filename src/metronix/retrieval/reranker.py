"""Cross-encoder reranker for search results.

Uses BAAI/bge-reranker-v2-m3 to rerank hybrid search results by semantic
relevance. Lazy-loads the model on first call (singleton via lru_cache).
"""

from __future__ import annotations

import threading

import structlog

logger = structlog.get_logger()

_reranker = None
_reranker_lock = threading.Lock()


def _get_reranker():
    """Lazy-load cross-encoder model (thread-safe singleton)."""
    global _reranker
    if _reranker is not None:
        return _reranker
    with _reranker_lock:
        if _reranker is not None:
            return _reranker
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
        logger.info("reranker.loaded", model="BAAI/bge-reranker-v2-m3")
        return _reranker


def rerank(query: str, results: list[dict], top_k: int = 25) -> list[dict]:
    """Rerank search results using cross-encoder.

    Args:
        query: User query string.
        results: List of search result dicts with 'memory' or 'data' text field.
        top_k: Number of results to return after reranking.

    Returns:
        Top-k results sorted by cross-encoder relevance score.
    """
    if not results or len(results) <= 1:
        return results

    model = _get_reranker()

    pairs = []
    for r in results:
        text = r.get("memory") or r.get("data") or ""
        pairs.append((query, text[:512]))

    scores = model.predict(pairs)

    for r, score in zip(results, scores, strict=False):
        r["rerank_score"] = float(score)

    results.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
    return results[:top_k]
