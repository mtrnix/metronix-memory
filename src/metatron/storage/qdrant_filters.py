"""Qdrant filter/query helpers and module-level factory.

Extends QdrantVectorStore with filter-based search and statistics methods.
Also provides the cached factory ``get_hybrid_store()`` and ``clear_store_cache()``.

Migrated from PoC: metatron_experiments/metatron/indexers/hybrid_store_workspace.py
"""

from __future__ import annotations

import structlog
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from metatron.storage.qdrant import QdrantVectorStore

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Filter-based search methods (scroll, no vector query)
# ---------------------------------------------------------------------------


def search_by_date(store: QdrantVectorStore, dates: list[str], limit: int = 10) -> list[dict]:
    """Search by date filter using MatchAny."""
    if not dates:
        return []
    filter_cond = Filter(must=[FieldCondition(key="date", match=MatchAny(any=dates))])
    results, _ = store.client.scroll(
        collection_name=store.collection_name,
        scroll_filter=filter_cond,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [store._format_result(p, 1.0) for p in results]


def search_by_type(store: QdrantVectorStore, doc_type: str, limit: int = 10) -> list[dict]:
    """Search by document type filter."""
    filter_cond = Filter(must=[FieldCondition(key="type", match=MatchValue(value=doc_type))])
    results, _ = store.client.scroll(
        collection_name=store.collection_name,
        scroll_filter=filter_cond,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [store._format_result(p, 1.0) for p in results]


def search_by_doc_labels(
    store: QdrantVectorStore, doc_labels: list[str], limit: int = 10
) -> list[dict]:
    """Search by document label filter."""
    labels = [label for label in doc_labels if label]
    if not labels:
        return []
    match = MatchAny(any=labels) if len(labels) > 1 else MatchValue(value=labels[0])
    filter_cond = Filter(must=[FieldCondition(key="doc_label", match=match)])
    results, _ = store.client.scroll(
        collection_name=store.collection_name,
        scroll_filter=filter_cond,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [store._format_result(p, 1.0) for p in results]


# ---------------------------------------------------------------------------
# Collection info / stats
# ---------------------------------------------------------------------------


def get_collection_info(store: QdrantVectorStore) -> dict:
    """Get collection statistics."""
    try:
        info = store.client.get_collection(store.collection_name)
        return {
            "name": store.collection_name,
            "workspace_id": store.workspace_id,
            "points_count": info.points_count,
            "status": str(info.status),
        }
    except Exception as e:
        logger.error("qdrant.collection_info.error", workspace_id=store.workspace_id, error=str(e))
        return {
            "name": store.collection_name,
            "workspace_id": store.workspace_id,
            "points_count": 0,
            "status": "error",
        }


def get_stats(store: QdrantVectorStore) -> dict:
    """Get detailed statistics: chunk count and unique file count.

    Delegates to the instance method ``QdrantVectorStore.get_stats()``.
    """
    return store.get_stats()


# Re-export from main module for backward compatibility
from metatron.storage.qdrant import clear_store_cache, get_hybrid_store  # noqa: F401, E402
