"""Request/response models for MCP tools.

All Pydantic models used by the MCP tool functions live here
to avoid circular imports and keep tool files focused.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Search ---

class SearchResultItem(BaseModel):
    """Single search result item."""

    doc_label: str
    title: str
    content: str
    source_type: str
    timestamp: Optional[str] = None
    score: float = 0.0


class SearchResponse(BaseModel):
    """Response from metatron_search tool."""

    results: list[SearchResultItem]
    has_more: bool
    next_cursor: Optional[str] = None
    total: int


# --- Get ---

class DocumentResponse(BaseModel):
    """Response from metatron_get tool."""

    doc_label: str
    title: str
    content: str
    source_type: str
    timestamp: Optional[str] = None
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
    last_sync: Optional[str] = None
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
