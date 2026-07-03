"""Memory REST API — /api/v1/memory.

Exposes persistent + session agent-memory operations with workspace scoping
and RBAC. Workspace is always derived from the authenticated user — never
accepted from the request body or query string.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime  # noqa: TC003 — pydantic field validation needs runtime resolution
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from metronix.api.dependencies import (
    get_memory_service,
    resolve_workspace_id,
    workspace_scope,
)
from metronix.auth.dependencies import require_editor, require_viewer
from metronix.core.exceptions import MemoryNotFoundError
from metronix.core.models import (
    LifecycleStatus,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    ReviewEntry,
    User,
)
from metronix.memory.service import (
    MemoryService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(workspace_scope)])


# ---------------------------------------------------------------------------
# Pydantic v2 schemas
# ---------------------------------------------------------------------------


class CreateMemoryRecordRequest(BaseModel):
    """Request body for creating a memory record."""

    model_config = ConfigDict(strict=False)

    content: str = Field(..., min_length=1, max_length=32768)
    agent_id: str = Field(..., min_length=1, max_length=128)
    scope: MemoryScope = MemoryScope.PER_AGENT
    source_type: str = Field("", max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=32)
    importance_score: float = Field(0.5, ge=0.0, le=1.0)
    ttl_expires_at: datetime | None = None
    session_id: str | None = Field(None, min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    kind: MemoryKind = MemoryKind.FACT  # MTRNIX-275

    @model_validator(mode="after")
    def validate_after(self) -> CreateMemoryRecordRequest:
        if self.scope == MemoryScope.SESSION and self.session_id is None:
            raise ValueError("session_id is required when scope=SESSION")
        for tag in self.tags:
            if len(tag) > 64:
                raise ValueError("tag length must not exceed 64 characters")
        # Bound metadata size to protect storage from runaway payloads.
        if len(self.metadata) > 64:
            raise ValueError("metadata must not contain more than 64 keys")
        if len(json.dumps(self.metadata, default=str)) > 32768:
            raise ValueError("metadata serialized size must not exceed 32 KiB")
        return self


class MemoryRecordResponse(BaseModel):
    """Response body for a single memory record."""

    id: str
    workspace_id: str
    agent_id: str
    scope: MemoryScope
    source_type: str
    content: str
    tags: list[str]
    importance_score: float
    ttl_expires_at: datetime | None
    content_hash: str
    created_at: datetime
    session_id: str | None
    metadata: dict[str, Any]
    status: LifecycleStatus  # MTRNIX-324 — never optional; MemoryRecord.status defaults to ACTIVE
    kind: MemoryKind  # MTRNIX-275 — never optional; MemoryRecord.kind defaults to FACT


class MemorySearchRequest(BaseModel):
    """Request body for hybrid memory search."""

    model_config = ConfigDict(strict=False)

    query: str = Field(..., min_length=1, max_length=2048)
    agent_id: str | None = Field(None, min_length=1, max_length=128)
    scope: MemoryScope | None = None
    tags: list[str] | None = None
    session_id: str | None = Field(None, min_length=1, max_length=128)
    top_k: int = Field(5, ge=1, le=50)
    # MTRNIX-324: None means "apply default exclusion" (ARCHIVED + SUPERSEDED excluded).
    # To override, pass an explicit list of lifecycle statuses to include.
    # Note: the "all" sentinel accepted by MCP is not valid here — REST consumers
    # must send a list of explicit LifecycleStatus enum values or omit the field.
    status_filter: list[LifecycleStatus] | None = None


class MemorySearchResultResponse(BaseModel):
    """Response body for a single memory search hit."""

    record: MemoryRecordResponse
    score: float
    dense_score: float
    sparse_score: float
    graph_score: float
    rank: int


class MemorySearchResponse(BaseModel):
    """Response body for a memory search call."""

    results: list[MemorySearchResultResponse]
    count: int


class MemoryRecordListResponse(BaseModel):
    """Response body for listing memory records.

    ``count`` is the size of the current page; ``total`` is the number of
    records matching the request filters across all pages (before
    limit/offset).
    """

    records: list[MemoryRecordResponse]
    count: int
    total: int
    limit: int
    offset: int
    has_more: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_to_response(record: MemoryRecord) -> MemoryRecordResponse:
    """Convert a MemoryRecord dataclass into its Pydantic response."""
    return MemoryRecordResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        agent_id=record.agent_id,
        scope=record.scope,
        source_type=record.source_type,
        content=record.content,
        tags=list(record.tags),
        importance_score=record.importance_score,
        ttl_expires_at=record.ttl_expires_at,
        content_hash=record.content_hash,
        created_at=record.created_at,
        session_id=record.session_id,
        metadata=dict(record.metadata),
        status=record.status,  # MTRNIX-324
        kind=record.kind,  # MTRNIX-275
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/records",
    response_model=MemoryRecordResponse,
    status_code=201,
)
async def create_record(
    body: CreateMemoryRecordRequest,
    request: Request,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRecordResponse:
    """Create a memory record.

    SESSION-scoped records are cached in Redis (with TTL); all other scopes
    are persisted in Qdrant (plus best-effort Neo4j).
    """
    workspace_id = resolve_workspace_id(request)
    record = MemoryRecord(
        workspace_id=workspace_id,
        agent_id=body.agent_id,
        scope=body.scope,
        kind=body.kind,
        source_type=body.source_type,
        content=body.content,
        tags=list(body.tags),
        importance_score=body.importance_score,
        ttl_expires_at=body.ttl_expires_at,
        session_id=body.session_id,
        metadata=dict(body.metadata),
    )

    if body.scope == MemoryScope.SESSION:
        session_id = body.session_id
        if session_id is None:  # Defense in depth — validator enforces this too.
            raise HTTPException(
                status_code=422,
                detail="session_id is required when scope=SESSION",
            )
        stored = await service.cache_session(workspace_id, session_id, record)
    else:
        stored = await service.save(workspace_id, record)

    return _record_to_response(stored)


# Statuses excluded by default when no explicit status_filter is given to
# the search endpoint. The list endpoint does NOT apply this default.
_DEFAULT_SEARCH_EXCLUDE = frozenset({LifecycleStatus.ARCHIVED, LifecycleStatus.SUPERSEDED})


@router.post("/search", response_model=MemorySearchResponse)
async def search_records(
    body: MemorySearchRequest,
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemorySearchResponse:
    """Run a hybrid dense+sparse+graph search over memory records.

    Default status filter excludes ARCHIVED and SUPERSEDED — only ACTIVE,
    CANDIDATE, STALE, CONFLICTED, and REVIEW_NEEDED records are returned.
    Pass an explicit ``status_filter`` list to override this default.
    Note: the MCP ``"all"`` sentinel is not accepted here; pass each status
    value explicitly (e.g. ``["active", "archived"]``) to include all.
    """
    workspace_id = resolve_workspace_id(request)
    results: list[MemorySearchResult]

    # Apply route-layer default — mirrors the MCP layer pattern where the
    # MCP tool applies ``parse_status_filter`` before calling the service.
    # The REST default (exclude ARCHIVED + SUPERSEDED) is broader than the
    # MCP default (only ACTIVE) per MTRNIX-324 spec. MTRNIX-R2.
    if body.status_filter is None:
        effective_status_filter: list[LifecycleStatus] | None = [
            s for s in LifecycleStatus if s not in _DEFAULT_SEARCH_EXCLUDE
        ]
    else:
        effective_status_filter = body.status_filter

    try:
        results = await service.search(
            workspace_id,
            body.query,
            agent_id=body.agent_id,
            scope=body.scope,
            tags=body.tags,
            session_id=body.session_id,
            top_k=body.top_k,
            status_filter=effective_status_filter,
        )
    except RuntimeError as exc:
        if "search not configured" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="Memory search is not configured",
            ) from None
        raise

    return MemorySearchResponse(
        results=[
            MemorySearchResultResponse(
                record=_record_to_response(r.record),
                score=r.score,
                dense_score=r.dense_score,
                sparse_score=r.sparse_score,
                graph_score=r.graph_score,
                rank=r.rank,
            )
            for r in results
        ],
        count=len(results),
    )


@router.get("/records", response_model=MemoryRecordListResponse)
async def list_records(
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
    agent_id: str | None = Query(None, min_length=1, max_length=128),
    scope: MemoryScope | None = None,
    session_id: str | None = Query(None, min_length=1, max_length=128),
    status_filter: list[LifecycleStatus] | None = Query(None),  # noqa: B008
    kind_filter: list[MemoryKind] | None = Query(None),  # noqa: B008
    source_type_filter: list[str] | None = Query(None),  # noqa: B008
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> MemoryRecordListResponse:
    """List memory records for the current workspace.

    When ``session_id`` is provided, returns Redis-backed session records
    and ignores ``agent_id``/``scope`` filters. Otherwise returns persistent
    records from PG, paginated with limit+offset.

    Unlike the search endpoint, this list endpoint does NOT apply a default
    status exclusion — all lifecycle states are returned unless ``status_filter``
    is explicitly set. This is intentional: the inspector UI needs to see all
    records including ARCHIVED and SUPERSEDED.
    """
    workspace_id = resolve_workspace_id(request)

    if session_id is not None:
        session_records = await service.list_session(workspace_id, session_id)
        return MemoryRecordListResponse(
            records=[_record_to_response(r) for r in session_records],
            count=len(session_records),
            total=len(session_records),
            limit=limit,
            offset=offset,
            has_more=False,
        )

    records, total = await asyncio.gather(
        service.list_records(
            workspace_id,
            agent_id=agent_id,
            scope=scope,
            kind_filter=kind_filter,
            source_type_filter=source_type_filter,
            status=status_filter,
            limit=limit,
            offset=offset,
        ),
        service.count_records(
            workspace_id,
            agent_id=agent_id,
            scope=scope,
            kind_filter=kind_filter,
            source_type_filter=source_type_filter,
            status=status_filter,
        ),
    )
    return MemoryRecordListResponse(
        records=[_record_to_response(r) for r in records],
        count=len(records),
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(records)) < total,
    )


@router.get("/records/{record_id}", response_model=MemoryRecordResponse)
async def get_record(
    record_id: str,
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRecordResponse:
    """Fetch a single persistent memory record by id.

    Returns 404 when the record does not exist in the current workspace —
    including when a record exists but belongs to a different workspace
    (cross-workspace isolation guaranteed by PG ``WHERE workspace_id = :ws``).
    """
    workspace_id = resolve_workspace_id(request)
    record = await service.get(workspace_id, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return _record_to_response(record)


class MemoryGraphEdge(BaseModel):
    """An edge in the memory neighbourhood graph.

    For bridge-mediated edges (REMEMBERS / ABOUT / FROM_SESSION / DERIVED_FROM),
    ``metadata`` contains ``{"via": "<NodeLabel>", "via_id": "<bridge-node-id>"}``
    so the UI can surface "shared agent X" without a direct memory-to-memory edge.

    For ``LINKED_TO`` edges created by the Linker stage, ``metadata`` holds the
    edge properties (e.g. ``{"score": 0.9}``).
    """

    source: str
    target: str
    type: Literal["REMEMBERS", "ABOUT", "FROM_SESSION", "DERIVED_FROM", "LINKED_TO"]
    metadata: dict[str, Any] | None = None


class MemoryGraphResponse(BaseModel):
    """Response for the memory neighbourhood graph endpoint."""

    nodes: list[MemoryRecordResponse]
    edges: list[MemoryGraphEdge]


@router.get("/graph", response_model=MemoryGraphResponse)
async def get_memory_graph(
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
    seed_record_id: str = Query(..., min_length=1, max_length=128),
    depth: int = Query(1, ge=1, le=3),
    agent_id: str | None = Query(None, min_length=1, max_length=128),
) -> MemoryGraphResponse:
    """Return the neighbourhood graph around a memory record.

    **Nodes:** all ``MemoryRecord`` objects reachable within ``depth`` hops from
    ``seed_record_id``, hydrated from PG.

    **Edges:** connections between memory records, including bridge-mediated edges
    (via Agent / Entity / Session / Document) and direct ``LINKED_TO`` edges.

    The ``depth`` parameter applies to direct memory-to-memory traversal
    (``LINKED_TO`` chains, 1..``depth`` hops). Bridge edges via Agent / Entity /
    Session / Document are always returned at exactly 2 hops from the seed
    regardless of ``depth`` — Phase 1 semantics; deeper bridge expansion is a
    follow-up.

    When Neo4j is unavailable, returns the seed node only with an empty edge list
    (graceful degradation — 200 with partial data, warning logged).

    Use ``agent_id`` to filter the neighbourhood to records belonging to a
    specific agent. Edges are filtered to those whose both endpoints survive the
    agent filter.

    Workspace isolation: ``workspace_id`` comes from the JWT only.
    """
    workspace_id = resolve_workspace_id(request)
    records, raw_edges = await service.get_graph_neighborhood(
        workspace_id, seed_record_id, depth=depth
    )

    # Optional agent_id filter — keep only records for this agent.
    if agent_id is not None:
        records = [r for r in records if r.agent_id == agent_id]

    surviving_ids = {r.id for r in records}
    # Drop edges where either endpoint was filtered out.
    filtered_edges = [
        e for e in raw_edges if e["source"] in surviving_ids and e["target"] in surviving_ids
    ]

    return MemoryGraphResponse(
        nodes=[_record_to_response(r) for r in records],
        edges=[MemoryGraphEdge(**e) for e in filtered_edges],
    )


class ReviewEntryResponse(BaseModel):
    """Response body for a single review-queue entry."""

    id: str
    workspace_id: str
    target_id: str
    target_kind: str  # always "memory_record" for v1 — preserved for UI parity with MCP
    reason: str
    related_record_id: str | None
    content: str
    confidence: float
    created_at: datetime


class ReviewListResponse(BaseModel):
    """Paginated response for the review-queue list endpoint."""

    entries: list[ReviewEntryResponse]
    count: int
    total: int
    limit: int
    offset: int
    has_more: bool


class ReviewResolveRequest(BaseModel):
    """Request body for resolving a review entry."""

    model_config = ConfigDict(strict=False)

    action: Literal["keep", "archive", "merge_into", "discard"]
    target_record_id: str | None = Field(None, min_length=1, max_length=128)
    notes: str | None = Field(None, max_length=1024)

    @model_validator(mode="after")
    def _validate(self) -> ReviewResolveRequest:
        if self.action == "merge_into" and not self.target_record_id:
            raise ValueError("target_record_id is required when action=merge_into")
        if self.action != "merge_into" and self.target_record_id is not None:
            raise ValueError("target_record_id is only valid when action=merge_into")
        return self


def _entry_to_response(entry: ReviewEntry) -> ReviewEntryResponse:
    """Convert a ReviewEntry dataclass into its Pydantic response."""
    return ReviewEntryResponse(
        id=entry.id,
        workspace_id=entry.workspace_id,
        target_id=entry.target_id,
        target_kind=entry.target_kind,
        reason=entry.reason,
        related_record_id=entry.related_record_id,
        content=entry.content,
        confidence=entry.confidence,
        created_at=entry.created_at,
    )


@router.get("/review", response_model=ReviewListResponse)
async def list_review_entries(
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
    reason: str | None = Query(None, min_length=1, max_length=64),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
) -> ReviewListResponse:
    """List pending review-queue entries for the current workspace.

    Returns paginated ``ReviewEntry`` items produced by the freshness pipeline
    (e.g. possible duplicates, contradictions, low-confidence decisions).

    Returns 503 when the freshness store is not configured (e.g. the deployment
    does not run the freshness worker).
    """
    workspace_id = resolve_workspace_id(request)
    try:
        entries, total = await service.list_review_entries(
            workspace_id,
            reason=reason,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        if "freshness_store" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="Review queue not configured",
            ) from None
        raise
    has_more = (offset + len(entries)) < total
    return ReviewListResponse(
        entries=[_entry_to_response(e) for e in entries],
        count=len(entries),
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.post("/review/{review_id}", status_code=204)
async def resolve_review_entry(
    review_id: str,
    body: ReviewResolveRequest,
    request: Request,
    user: Annotated[User, Depends(require_editor)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> Response:
    """Resolve a pending review entry.

    Applies one of four actions to the referenced memory record:

    * ``keep`` — mark the record as ACTIVE (no-op if already ACTIVE).
    * ``archive`` — soft-delete by transitioning to ARCHIVED.
    * ``merge_into`` — merge content into ``target_record_id``; source becomes SUPERSEDED.
    * ``discard`` — same as archive but with a different audit label.

    After resolution the review row is deleted and a ``MachineEvent`` is appended with
    the authenticated user's id as the ``actor``.

    Returns 404 when the review entry or target record does not exist.
    Returns 503 when the freshness store is not configured.
    """
    workspace_id = resolve_workspace_id(request)
    if body.action == "merge_into":
        action_str = f"merge_into:{body.target_record_id}"
    else:
        action_str = body.action
    try:
        await service.resolve_review(
            workspace_id,
            review_id=review_id,
            action=action_str,
            notes=body.notes,
            actor=user.id,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        if "freshness_store" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="Review queue not configured",
            ) from None
        raise
    return Response(status_code=204)


@router.delete("/records/{record_id}", status_code=204)
async def delete_record(
    record_id: str,
    request: Request,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> Response:
    """Delete a persistent memory record by id. 404 if PG does not have it.

    Session records are managed separately via ``invalidate_session`` —
    this endpoint only touches the persistent stores (PG, Qdrant, Neo4j).
    """
    workspace_id = resolve_workspace_id(request)
    deleted = await service.delete(workspace_id, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return Response(status_code=204)
