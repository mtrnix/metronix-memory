"""Qdrant hybrid vector store with workspace isolation.

Combines dense (semantic) and sparse (BM25) vectors per workspace.
Each workspace gets its own Qdrant collection for complete data isolation.

Migrated from PoC: metatron_experiments/metatron/indexers/hybrid_store_workspace.py
"""
# TODO: migrate to AsyncQdrantClient
from __future__ import annotations

import uuid
from typing import List, Dict, Optional, Any

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, SparseVectorParams, Distance, PointStruct,
    SparseVector, Prefetch, FusionQuery, Filter,
    FieldCondition, MatchValue, MatchAny, MatchText,
)

from metatron.ingestion.bm25 import compute_bm25_sparse_vector, compute_query_sparse_vector
from metatron.llm.embeddings import get_cached_embedding, get_cached_embedding_split  # TODO: async migration

logger = structlog.get_logger()

BASE_COLLECTION_NAME = "mem_docs_hybrid"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"
DENSE_DIM = 768  # nomic-embed-text dimensions
DEFAULT_WORKSPACE_ID = "MTRNIX"


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    """Normalize workspace ID to canonical form."""
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def get_collection_name(workspace_id: Optional[str] = None) -> str:
    """Get Qdrant collection name for a workspace.
    Default workspace uses base name without suffix for backward compat."""
    workspace_id = _normalize_workspace_id(workspace_id)
    if workspace_id == DEFAULT_WORKSPACE_ID:
        return BASE_COLLECTION_NAME
    return f"{BASE_COLLECTION_NAME}_{workspace_id}"


class QdrantVectorStore:
    """Workspace-aware hybrid vector store (dense + sparse BM25)."""
    # TODO: async migration

    def __init__(self, workspace_id: Optional[str] = None,
                 host: str = "localhost", port: int = 6333) -> None:
        self.workspace_id = _normalize_workspace_id(workspace_id)
        self.collection_name = get_collection_name(workspace_id)
        self.client = QdrantClient(host=host, port=port, timeout=60)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist with hybrid vector config."""
        collections = self.client.get_collections().collections
        if any(c.name == self.collection_name for c in collections):
            logger.debug("qdrant.collection.exists", collection=self.collection_name)
            return
        logger.info("qdrant.collection.creating", workspace_id=self.workspace_id,
                    collection=self.collection_name)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(size=DENSE_DIM, distance=Distance.COSINE)
            },
            sparse_vectors_config={SPARSE_VECTOR_NAME: SparseVectorParams()},
        )
        logger.info("qdrant.collection.created", dense_dim=DENSE_DIM, sparse="bm25")

        # Index for access_groups (used by enterprise ACL pre-filter)
        # No-op on points without this field — backward compatible
        try:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="access_groups",
                field_schema="keyword",
            )
        except Exception:
            pass  # Index may already exist on re-creation

    def _format_result(self, point: Any, score: float) -> Dict:
        """Format a Qdrant point into a standardized result dict."""
        payload = point.payload or {}
        data = payload.get("data") or payload.get("memory") or ""
        return {
            "id": str(point.id), "score": score, "memory": data, "data": data,
            "title": payload.get("title", ""), "type": payload.get("type", ""),
            "url": payload.get("url", ""),
            "date": payload.get("date", ""), "doc_label": payload.get("doc_label", ""),
            "workspace_id": payload.get("workspace_id", ""), "payload": payload,
            "source_role": payload.get("source_role", "knowledge_base"),
        }

    def add_document(self, text: str, metadata: Optional[Dict[str, Any]] = None,
                     doc_id: Optional[str] = None) -> list[str]:
        """Add document with both dense and sparse vectors.

        If the text exceeds the embedding model context window, it is
        automatically split and each sub-chunk is stored as a separate
        Qdrant point (all sharing the same metadata/doc_id).

        Returns list of Qdrant UUIDs (one per stored point).
        """
        if doc_id is not None:
            metadata = metadata or {}
            metadata["original_id"] = doc_id
        metadata = metadata or {}
        metadata["workspace_id"] = self.workspace_id

        # Get embeddings — may return multiple (text, embedding) on split
        embedding_pairs = get_cached_embedding_split(text)

        title = (metadata or {}).get("title", "")
        points: list[PointStruct] = []
        qdrant_ids: list[str] = []

        for chunk_text, dense_vector in embedding_pairs:
            qdrant_id = str(uuid.uuid4())
            qdrant_ids.append(qdrant_id)

            bm25_text = f"{title} {title} {chunk_text}" if title else chunk_text
            sparse_indices, sparse_values = compute_bm25_sparse_vector(bm25_text)

            payload = {**metadata}
            payload["data"] = chunk_text
            payload["memory"] = chunk_text  # backward compatibility

            points.append(PointStruct(
                id=qdrant_id,
                vector={
                    DENSE_VECTOR_NAME: dense_vector,
                    SPARSE_VECTOR_NAME: SparseVector(
                        indices=sparse_indices, values=sparse_values,
                    ),
                },
                payload=payload,
            ))

        if len(embedding_pairs) > 1:
            logger.info(
                "qdrant.add_document.split",
                doc_id=doc_id,
                sub_chunks=len(embedding_pairs),
            )

        self.client.upsert(collection_name=self.collection_name, points=points)
        return qdrant_ids

    def hybrid_search(self, query: str, limit: int = 10,
                      filter_conditions: Optional[Filter] = None,
                      dense_weight: float = 0.7, sparse_weight: float = 0.3) -> List[Dict]:
        """Hybrid search via Reciprocal Rank Fusion (RRF)."""
        dense_query = get_cached_embedding(query)
        sparse_indices, sparse_values = compute_query_sparse_vector(query)
        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    Prefetch(query=dense_query, using=DENSE_VECTOR_NAME,
                             limit=limit * 3, filter=filter_conditions),
                    Prefetch(query=SparseVector(indices=sparse_indices, values=sparse_values),
                             using=SPARSE_VECTOR_NAME,
                             limit=limit * 3, filter=filter_conditions),
                ],
                query=FusionQuery(fusion="rrf"), limit=limit, with_payload=True,
            )
            return [self._format_result(p, p.score) for p in results.points]
        except Exception as e:
            logger.warning("qdrant.hybrid_search.fallback",
                           workspace_id=self.workspace_id, error=str(e))
            return self.dense_search(query, limit=limit, filter_conditions=filter_conditions)

    def dense_search(self, query: str, limit: int = 10,
                     filter_conditions: Optional[Filter] = None) -> List[Dict]:
        """Dense-only (semantic) search."""
        dense_query = get_cached_embedding(query)
        results = self.client.query_points(
            collection_name=self.collection_name, query=dense_query,
            using=DENSE_VECTOR_NAME, limit=limit,
            query_filter=filter_conditions, with_payload=True,
        )
        return [self._format_result(p, p.score) for p in results.points]

    def keyword_search(self, query: str, limit: int = 10,
                       filter_conditions: Optional[Filter] = None) -> List[Dict]:
        """Sparse-only (keyword/BM25) search."""
        sparse_indices, sparse_values = compute_query_sparse_vector(query)
        if not sparse_indices:
            return []
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=SparseVector(indices=sparse_indices, values=sparse_values),
            using=SPARSE_VECTOR_NAME, limit=limit,
            query_filter=filter_conditions, with_payload=True,
        )
        return [self._format_result(p, p.score) for p in results.points]

    def clear(self) -> None:
        """Delete and recreate collection for this workspace."""
        try:
            self.client.delete_collection(self.collection_name)
            logger.info("qdrant.collection.deleted", collection=self.collection_name)
        except Exception as e:
            logger.error("qdrant.collection.delete_error", error=str(e))
        self._ensure_collection()

    def search_by_date(self, dates: List[str], limit: int = 10) -> List[Dict]:
        """Filter search by date values."""
        if not dates:
            return []
        filt = Filter(must=[FieldCondition(key="date", match=MatchAny(any=dates))])
        results, _ = self.client.scroll(collection_name=self.collection_name,
            scroll_filter=filt, limit=limit, with_payload=True, with_vectors=False)
        return [self._format_result(p, 1.0) for p in results]

    def search_by_type(self, doc_type: str, limit: int = 10) -> List[Dict]:
        """Filter search by document type."""
        filt = Filter(must=[FieldCondition(key="type", match=MatchValue(value=doc_type))])
        results, _ = self.client.scroll(collection_name=self.collection_name,
            scroll_filter=filt, limit=limit, with_payload=True, with_vectors=False)
        return [self._format_result(p, 1.0) for p in results]

    def search_by_doc_labels(self, doc_labels: List[str], limit: int = 10) -> List[Dict]:
        """Filter search by document labels."""
        labels = [lb for lb in doc_labels if lb]
        if not labels:
            return []
        m = MatchAny(any=labels) if len(labels) > 1 else MatchValue(value=labels[0])
        filt = Filter(must=[FieldCondition(key="doc_label", match=m)])
        results, _ = self.client.scroll(collection_name=self.collection_name,
            scroll_filter=filt, limit=limit, with_payload=True, with_vectors=False)
        return [self._format_result(p, 1.0) for p in results]

    def search_by_status(self, status: str, limit: int = 20) -> List[Dict]:
        """Filter search by status metadata field (e.g. 'In Progress', 'Done')."""
        filt = Filter(must=[FieldCondition(key="status", match=MatchValue(value=status))])
        results, _ = self.client.scroll(collection_name=self.collection_name,
            scroll_filter=filt, limit=limit, with_payload=True, with_vectors=False)
        return [self._format_result(p, 1.0) for p in results]

    def search_by_assignee(self, assignee: str, limit: int = 20) -> List[Dict]:
        """Filter search by assignee (exact match)."""
        filt = Filter(must=[FieldCondition(key="assignee", match=MatchValue(value=assignee))])
        results, _ = self.client.scroll(collection_name=self.collection_name,
            scroll_filter=filt, limit=limit, with_payload=True, with_vectors=False)
        return [self._format_result(p, 1.0) for p in results]

    def scroll_by_title(self, title_substring: str, limit: int = 5) -> List[Dict]:
        """Scroll points where title contains substring (case-insensitive via MatchText)."""
        if not title_substring or not title_substring.strip():
            return []
        filt = Filter(must=[
            FieldCondition(key="title", match=MatchText(text=title_substring)),
        ])
        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=filt, limit=limit,
            with_payload=True, with_vectors=False,
        )
        return [self._format_result(p, 1.0) for p in results]

    def delete_by_doc_labels(self, doc_labels: list[str]) -> int:
        """Delete all points matching any of the given doc_labels.

        Used during incremental sync to remove old chunks before re-ingesting
        an updated document.

        Returns:
            Number of points deleted.
        """
        if not doc_labels:
            return 0
        match = MatchAny(any=doc_labels) if len(doc_labels) > 1 else MatchValue(value=doc_labels[0])
        filt = Filter(must=[FieldCondition(key="doc_label", match=match)])
        try:
            # Count existing points before delete
            existing, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=filt, limit=100, with_payload=False, with_vectors=False,
            )
            count = len(existing)
            if count == 0:
                return 0
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=filt,
            )
            logger.info("qdrant.delete_by_doc_labels", doc_labels=doc_labels[:5], deleted=count)
            return count
        except Exception as e:
            logger.error("qdrant.delete_by_doc_labels.error", error=str(e))
            return 0

    def get_stats(self) -> Dict:
        """Get workspace statistics: chunk count and unique file count.

        # TODO: Read file_count/chunk_count from PostgreSQL instead of scanning Qdrant.
        # Current implementation scrolls all points on every /stats call — acceptable for MVP
        # but must be replaced with cached counters in PostgreSQL once persistence is implemented.
        # Counters should be updated during ingest_documents() and delete operations.
        """
        try:
            info = self.client.get_collection(self.collection_name)
            chunk_count = info.points_count or 0
            file_count = 0

            if chunk_count > 0:
                labels: set[str] = set()
                offset = None
                while True:
                    results, offset = self.client.scroll(
                        collection_name=self.collection_name,
                        limit=100, offset=offset,
                        with_payload=["doc_label"], with_vectors=False,
                    )
                    for point in results:
                        label = point.payload.get("doc_label")
                        if label:
                            labels.add(label)
                    if offset is None:
                        break
                file_count = len(labels)

            return {"chunk_count": chunk_count, "file_count": file_count}
        except Exception as e:
            logger.error("qdrant.stats.error",
                         workspace_id=self.workspace_id, error=str(e))
            return {"chunk_count": 0, "file_count": 0}

    def delete(self) -> None:
        """Delete the collection permanently."""
        try:
            self.client.delete_collection(self.collection_name)
            logger.info("qdrant.collection.deleted_permanently",
                        collection=self.collection_name)
        except Exception as e:
            logger.error("qdrant.collection.delete_error", error=str(e))


# ---------------------------------------------------------------------------
# Module-level factory (cached singleton per workspace)
# ---------------------------------------------------------------------------
from threading import Lock  # noqa: E402

_hybrid_stores: Dict[str, QdrantVectorStore] = {}
_store_lock = Lock()


def get_hybrid_store(workspace_id: Optional[str] = None,
                     host: Optional[str] = None,
                     port: Optional[int] = None) -> QdrantVectorStore:
    """Get or create QdrantVectorStore for a workspace (cached singleton).

    Host/port default to values from Settings (env vars) when not provided.
    """
    ws = _normalize_workspace_id(workspace_id)
    if ws not in _hybrid_stores:
        with _store_lock:
            if ws not in _hybrid_stores:
                if host is None or port is None:
                    from metatron.core.config import get_settings
                    s = get_settings()
                    host = host or s.qdrant_host
                    port = port or s.qdrant_http_port
                _hybrid_stores[ws] = QdrantVectorStore(workspace_id, host=host, port=port)
    return _hybrid_stores[ws]


def clear_store_cache() -> None:
    """Clear all cached QdrantVectorStore instances."""
    global _hybrid_stores
    _hybrid_stores = {}
