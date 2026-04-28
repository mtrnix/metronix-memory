"""Qdrant vector store for Agent Memory (WS1).

Dedicated collection per workspace for memory records.
Stores content text + dense/sparse embeddings for hybrid search.
Separate from document collection (different payload schema, scoring).

This is an L1 storage module.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from metatron.core.config import get_settings
from metatron.llm.embeddings import get_cached_embedding
from metatron.storage.qdrant import _compute_doc_sparse, _compute_query_sparse

if TYPE_CHECKING:
    from metatron.core.models import MemoryRecord

logger = structlog.get_logger()

_COLLECTION_PREFIX = "mem_agent_memory"
_DENSE_NAME = "dense"
_SPARSE_NAME = "bm25"
_DENSE_DIM = 768


def _collection_name(workspace_id: str) -> str:
    return f"{_COLLECTION_PREFIX}_{workspace_id}"


class MemoryQdrantStore:
    """Async Qdrant store for agent memory records.

    Each workspace gets a dedicated collection with hybrid vectors
    (dense + sparse). Collection is lazily created on first operation.
    """

    def __init__(
        self,
        workspace_id: str = "MTRNIX",
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        settings = get_settings()
        self._workspace_id = workspace_id
        self._collection = _collection_name(workspace_id)
        self._client = AsyncQdrantClient(
            host=host or settings.qdrant_host,
            port=port or settings.qdrant_http_port,
            timeout=60,
            api_key=settings.qdrant_api_key or None,
            https=settings.qdrant_https,
        )
        self._collection_ensured = False

    async def _ensure_collection(self) -> None:
        """Create memory collection if it doesn't exist."""
        if self._collection_ensured:
            return
        collections = await self._client.get_collections()
        if any(c.name == self._collection for c in collections.collections):
            self._collection_ensured = True
            return

        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                _DENSE_NAME: VectorParams(size=_DENSE_DIM, distance=Distance.COSINE),
            },
            sparse_vectors_config={_SPARSE_NAME: SparseVectorParams()},
        )
        # Payload indexes for filtered search
        for field in ("agent_id", "scope", "kind"):
            try:
                await self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                logger.warning("memory_qdrant.index.failed", field=field)
        logger.info("memory_qdrant.collection.created", collection=self._collection)
        self._collection_ensured = True

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    async def upsert(self, record: MemoryRecord) -> None:
        """Store a memory record with dense + sparse vectors.

        Generates embeddings from record.content. Uses record.id as
        the Qdrant point ID for deterministic updates.

        Note: ``metadata``, ``session_id``, and ``content_hash`` are
        intentionally omitted from the Qdrant payload. Qdrant is for
        vector search, not full record storage (PG handles that).
        """
        await self._ensure_collection()

        dense_vector = await asyncio.to_thread(get_cached_embedding, record.content)
        sparse_indices, sparse_values = await asyncio.to_thread(
            _compute_doc_sparse,
            record.content,
        )

        payload: dict[str, Any] = {
            "content": record.content,
            "record_id": record.id,
            "workspace_id": record.workspace_id,
            "agent_id": record.agent_id,
            "scope": record.scope.value,
            "source_type": record.source_type,
            "tags": record.tags,
            "importance_score": record.importance_score,
            "created_at": record.created_at.isoformat(),
            # MTRNIX-314: lifecycle status so search-time filter pushes down.
            # Legacy points written before this change have no ``status`` key;
            # exclude-filter semantics treat missing-as-ACTIVE (correct default).
            "status": record.status.value,
            # MTRNIX-275: kind so assembler/retrieval can filter by category.
            "kind": record.kind.value,
        }

        point = PointStruct(
            id=record.id,
            vector={
                _DENSE_NAME: dense_vector,
                _SPARSE_NAME: SparseVector(
                    indices=sparse_indices,
                    values=sparse_values,
                ),
            },
            payload=payload,
        )

        await self._client.upsert(
            collection_name=self._collection,
            points=[point],
        )
        logger.debug("memory_qdrant.upserted", record_id=record.id)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        scope: str | None = None,
        top_k: int = 5,
        status_exclude: list[str] | None = None,
        kind_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid dense+sparse search over memory records.

        Uses server-side RRF fusion. Workspace is scoped at __init__ time.
        Returns list of dicts with record payload + score.

        ``status_exclude`` (MTRNIX-314): if non-empty, the Qdrant query filter
        grows a ``must_not`` clause that excludes any point whose ``status``
        payload matches one of the listed values. Legacy points without a
        ``status`` field are not excluded (they behave as ``active``).
        ``kind_filter`` (MTRNIX-275): if non-empty, only points whose ``kind``
        payload matches one of the listed values are returned. When the filter
        contains only ``"fact"``, it is skipped entirely so that legacy points
        without a ``kind`` field are included (backward compat — they default
        to fact). Non-fact-only filters (e.g. ``["preference", "pinned"]``)
        are applied as-is.
        """
        await self._ensure_collection()

        dense_vector = await asyncio.to_thread(get_cached_embedding, query)
        sparse_indices, sparse_values = await asyncio.to_thread(
            _compute_query_sparse,
            query,
        )

        # Build optional filter
        conditions = []
        if agent_id:
            conditions.append(
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            )
        if scope:
            conditions.append(
                FieldCondition(key="scope", match=MatchValue(value=scope)),
            )

        if kind_filter:
            # When filtering to fact-only, skip the filter — legacy points
            # without a ``kind`` payload are treated as fact (backward
            # compat, DD-6 in plan). Only apply the filter when it
            # excludes facts (e.g. preference/pinned only).
            non_fact_kinds = [k for k in kind_filter if k != "fact"]
            if non_fact_kinds or "fact" not in kind_filter:
                conditions.append(
                    FieldCondition(key="kind", match=MatchAny(any=list(kind_filter))),
                )

        must_not_conditions: list[FieldCondition] = []
        if status_exclude:
            must_not_conditions.append(
                FieldCondition(key="status", match=MatchAny(any=list(status_exclude)))
            )

        qfilter: Filter | None
        if conditions or must_not_conditions:
            qfilter = Filter(
                must=conditions or None,  # type: ignore[arg-type]
                must_not=must_not_conditions or None,  # type: ignore[arg-type]
            )
        else:
            qfilter = None

        # Dense-first search with optional filter.
        # Avoids query_points+Prefetch+Fusion.RRF which breaks on
        # qdrant-client 1.16 → Qdrant server 1.17 version mismatch.
        results = await self._client.query_points(
            collection_name=self._collection,
            query=dense_vector,
            using=_DENSE_NAME,
            limit=top_k,
            query_filter=qfilter,
            with_payload=True,
        )

        return [
            {
                "record_id": (p.payload or {}).get("record_id", str(p.id)),
                "content": (p.payload or {}).get("content", ""),
                "score": p.score,
                "agent_id": (p.payload or {}).get("agent_id", ""),
                "scope": (p.payload or {}).get("scope", ""),
                "importance_score": (p.payload or {}).get("importance_score", 0.5),
                "tags": (p.payload or {}).get("tags", []),
                "payload": p.payload or {},
            }
            for p in results.points
        ]

    # ------------------------------------------------------------------
    # Get / Scroll
    # ------------------------------------------------------------------

    async def get(self, record_id: str) -> dict[str, Any] | None:
        """Fetch a single point by ID. Returns the same shape as ``search``/``scroll``.

        Returns None if not found.
        """
        await self._ensure_collection()
        points = await self._client.retrieve(
            collection_name=self._collection,
            ids=[record_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        p = points[0]
        return {
            "record_id": (p.payload or {}).get("record_id", str(p.id)),
            "content": (p.payload or {}).get("content", ""),
            "score": None,
            "agent_id": (p.payload or {}).get("agent_id", ""),
            "scope": (p.payload or {}).get("scope", ""),
            "importance_score": (p.payload or {}).get("importance_score", 0.5),
            "tags": (p.payload or {}).get("tags", []),
            "payload": p.payload or {},
        }

    async def scroll(
        self,
        agent_id: str | None,
        scope: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """List payloads filtered by agent_id/scope with in-process pagination.

        Qdrant's ``scroll`` uses cursors, not offsets; we over-fetch and slice
        in Python for simple offset semantics. Suitable for small result sets
        (the REST API caps limit at a modest value).
        """
        await self._ensure_collection()

        conditions = []
        if agent_id:
            conditions.append(
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            )
        if scope:
            conditions.append(
                FieldCondition(key="scope", match=MatchValue(value=scope)),
            )
        qfilter = Filter(must=conditions) if conditions else None  # type: ignore[arg-type]

        points, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=qfilter,
            limit=limit + offset,
            with_payload=True,
            with_vectors=False,
        )

        sliced = points[offset : offset + limit]
        return [
            {
                "record_id": (p.payload or {}).get("record_id", str(p.id)),
                "content": (p.payload or {}).get("content", ""),
                "score": None,
                "agent_id": (p.payload or {}).get("agent_id", ""),
                "scope": (p.payload or {}).get("scope", ""),
                "importance_score": (p.payload or {}).get("importance_score", 0.5),
                "tags": (p.payload or {}).get("tags", []),
                "payload": p.payload or {},
            }
            for p in sliced
        ]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, record_id: str) -> None:
        """Delete a single memory record by its ID (idempotent).

        Qdrant's ``delete`` does not distinguish missing from deleted — callers
        that need existence semantics should consult PostgreSQL (the source of
        truth in ``MemoryService.delete``).
        """
        await self._ensure_collection()
        await self._client.delete(
            collection_name=self._collection,
            points_selector=[record_id],
        )

    async def delete_by_agent(self, agent_id: str) -> None:
        """Delete all memory records for an agent."""
        await self._ensure_collection()
        await self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[
                    FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                ],
            ),
        )

    # ------------------------------------------------------------------
    # Update payload
    # ------------------------------------------------------------------

    async def update_payload(
        self,
        record_id: str,
        payload_updates: dict[str, Any],
    ) -> None:
        """Update payload fields on an existing point without re-embedding."""
        await self._ensure_collection()
        await self._client.set_payload(
            collection_name=self._collection,
            payload=payload_updates,
            points=[record_id],
        )
        logger.debug("memory_qdrant.payload_updated", record_id=record_id)

    async def close(self) -> None:
        """Close the Qdrant client."""
        await self._client.close()
