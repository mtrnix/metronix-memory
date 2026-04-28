"""Request/response models for MCP tools.

All Pydantic models used by the MCP tool functions live here
to avoid circular imports and keep tool files focused.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic needs runtime resolution for field types
from typing import Any

from pydantic import BaseModel, Field

# --- Search ---


class SearchResultItem(BaseModel):
    """Single search result item."""

    doc_label: str
    title: str
    content: str
    source_type: str
    timestamp: str | None = None
    score: float = 0.0


class SearchResponse(BaseModel):
    """Response from metatron_search tool."""

    results: list[SearchResultItem]
    has_more: bool
    next_cursor: str | None = None
    total: int


# --- Get ---


class DocumentResponse(BaseModel):
    """Response from metatron_get tool."""

    doc_label: str
    title: str
    content: str
    source_type: str
    timestamp: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Store ---


class StoreResponse(BaseModel):
    """Response from metatron_store tool."""

    success: bool
    doc_label: str
    chunks_stored: int


# --- Status ---


class StatusResponse(BaseModel):
    """Response from metatron_status tool."""

    status: str
    documents: dict[str, int]
    last_sync: str | None = None
    embedding_model: str


# --- Sync ---


class SyncSourceResult(BaseModel):
    """Result from syncing a single source."""

    source: str
    success: bool
    documents_fetched: int = 0
    documents_ingested: int = 0
    documents_skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    """Response from metatron_sync tool."""

    success: bool
    sources_synced: int
    details: list[SyncSourceResult]


# --- Memory ---


class MemoryRecordDTO(BaseModel):
    """Shape of a single memory record returned to MCP clients.

    Mirrors ``api.routes.memory.MemoryRecordResponse``; duplicated here so the
    MCP layer does not import pydantic schemas from the API layer.
    """

    id: str
    workspace_id: str
    agent_id: str
    scope: str
    source_type: str
    content: str
    tags: list[str] = Field(default_factory=list)
    importance_score: float = 0.0
    ttl_expires_at: datetime | None = None
    content_hash: str = ""
    created_at: datetime | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # MTRNIX-314: lifecycle status (lowercase LifecycleStatus value).
    # Default ``"active"`` keeps existing fixtures and callers working when the
    # record has no explicit status (legacy rows).
    status: str = "active"
    # MTRNIX-275: semantic category (fact/preference/pinned).
    kind: str = "fact"


class MemorySearchToolItem(BaseModel):
    """Single hit from metatron_memory_search."""

    record: MemoryRecordDTO
    score: float
    dense_score: float
    graph_score: float
    # Mirrors the reserved ``MemorySearchResult.sparse_score`` field (see
    # ``memory/.claude/CLAUDE.md``). Currently always 0.0 — Qdrant fuses
    # dense+sparse server-side via RRF. Kept on the MCP response for
    # forward-compat with a future client-side session-boost signal.
    session_boost: float
    rank: int


class MemorySearchToolResponse(BaseModel):
    """Response from metatron_memory_search tool."""

    results: list[MemorySearchToolItem]
    count: int


class MemoryStoreResponse(BaseModel):
    """Response from metatron_memory_store tool."""

    id: str
    content_hash: str
    deduped: bool


class MemoryDeleteResponse(BaseModel):
    """Response from metatron_memory_delete tool."""

    success: bool
    found: bool


# --- Fast search ---


class SearchFastItem(BaseModel):
    """Single hit from metatron_search_fast (no rerank / answer generation)."""

    doc_label: str = ""
    title: str = ""
    content: str = ""
    source_type: str = ""
    score: float = 0.0
    url: str = ""
    date: str = ""


class SearchFastResponse(BaseModel):
    """Response from metatron_search_fast tool."""

    results: list[SearchFastItem]
    count: int
    latency_ms: int


# --- Memory batch / list / update ---


class MemoryBatchStoreResult(BaseModel):
    """Result for a single record in a batch store operation."""

    id: str | None = None
    content_hash: str | None = None
    deduped: bool = False
    error: str | None = None


class MemoryBatchStoreResponse(BaseModel):
    """Response from memory_batch_store tool."""

    stored: int
    deduped: int
    results: list[MemoryBatchStoreResult]


class MemoryListResponse(BaseModel):
    """Response from memory_list tool."""

    records: list[MemoryRecordDTO]
    count: int
    total: int
    limit: int
    offset: int


class MemoryUpdateResponse(BaseModel):
    """Response from memory_update tool."""

    id: str
    content_hash: str
    updated_fields: list[str]


# --- Memory review queue (MTRNIX-314) ---


class ReviewEntryDTO(BaseModel):
    """Shape of a single review-queue row returned to MCP clients."""

    id: str
    workspace_id: str
    target_id: str
    target_kind: str = "memory_record"
    reason: str
    related_record_id: str | None = None
    content: str = ""
    confidence: float = 0.0
    created_at: datetime | None = None


class MemoryReviewListResponse(BaseModel):
    """Response from memory_review_list tool."""

    entries: list[ReviewEntryDTO]
    count: int
    total: int
    limit: int
    offset: int


class MemoryReviewResolveResponse(BaseModel):
    """Response from memory_review_resolve tool."""

    success: bool = True
    review_id: str
    target_id: str
    action: str
    old_status: str
    new_status: str
    superseded_by: str | None = None
    machine_event_id: str


# --- Memory context assembler (MTRNIX-275) ---


class MemoryContextResponse(BaseModel):
    """Response from metatron_memory_get_context MCP tool."""

    system_prompt: str
    preferences_count: int = 0
    memories_count: int = 0
