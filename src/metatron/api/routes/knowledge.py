"""Knowledge REST API — /api/v1/knowledge.

Exposes a unified, paginated view across agent memory (``memory_records``) and
KB documents (``raw_documents``) under a single endpoint.  The two sources are
fan-out concurrently under ``origin=all``.

Design decisions (see plan §8 Risks & decisions):
- ``workspace_id`` is always auth-derived via ``get_workspace_id(request)`` — it
  is never accepted from the query string or request body (D-P1-01).
- ``origin=all`` pagination is approximate: each leg fetches up to ``limit`` rows
  ordered by its own ``updated_at DESC``, then the combined page is re-sorted and
  truncated.  ``total = agent_total + kb_total`` is therefore an estimate when the
  two counts are used together with a merged page (D-P1-02).
- KB rows have no ``tags`` column → always ``[]``.  Do not synthesise from metadata
  (D-P1-03).
- KB ``connector_type`` is surfaced as ``source_type`` (D-P1-04).
- Hybrid search remains memory-only in Phase 1; this endpoint is list/inspect only
  (D-P1-05).

TODO (R2): for workspaces with >100 k raw_documents, ``count(*)`` becomes slow.
Consider adding a partial index or switching to ``EXPLAIN (FORMAT JSON) SELECT 1``
estimate.  Safe at current scale (< 500 documents).
"""

from __future__ import annotations

import asyncio
from datetime import datetime  # noqa: TC003 — pydantic field validation needs runtime resolution
from enum import Enum
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from metatron.api.dependencies import (
    get_memory_service,
    get_raw_document_service,
    get_workspace_id,
)
from metatron.auth.dependencies import require_viewer
from metatron.core.models import LifecycleStatus, RawDocument, User
from metatron.knowledge.service import (
    RawDocumentReadService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.memory.service import (
    MemoryService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class KnowledgeOrigin(str, Enum):
    """Origin discriminator for the knowledge endpoint.

    ``ALL`` is a query-string sentinel meaning "both sources"; it never appears
    in individual record responses (those always carry ``"agent"`` or ``"kb"``).
    """

    AGENT = "agent"
    KB = "kb"
    ALL = "all"


# ---------------------------------------------------------------------------
# Pydantic v2 schemas
# ---------------------------------------------------------------------------


class KnowledgeRecordResponse(BaseModel):
    """A single record in the unified knowledge view.

    ``origin`` is endpoint-derived, never stored: ``"agent"`` records come from
    ``memory_records``; ``"kb"`` records come from ``raw_documents``.
    ``agent_id`` is ``None`` for KB records.
    ``tags`` is always ``[]`` for KB records (no tags column on ``raw_documents``).
    ``source_type`` for KB records is mapped from ``RawDocument.connector_type``
    (values like ``"confluence"`` / ``"jira"`` are equally meaningful as either name).
    """

    id: str
    origin: Literal["agent", "kb"]
    content: str
    status: LifecycleStatus
    freshness_score: float
    source_type: str
    agent_id: str | None
    updated_at: datetime
    workspace_id: str
    tags: list[str]
    metadata: dict[str, Any]


class KnowledgeRecordListResponse(BaseModel):
    """Paginated response for ``GET /knowledge/records``."""

    records: list[KnowledgeRecordResponse]
    count: int
    limit: int
    offset: int
    has_more: bool
    partial: bool = False
    failed_sources: list[Literal["agent", "kb"]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Mapper helpers
# ---------------------------------------------------------------------------


def _memory_record_to_response(record: Any) -> KnowledgeRecordResponse:
    """Map a :class:`~metatron.core.models.MemoryRecord` to the unified shape."""
    return KnowledgeRecordResponse(
        id=record.id,
        origin="agent",
        content=record.content,
        status=record.status,
        freshness_score=getattr(record, "freshness_score", 0.5) or 0.5,
        source_type=record.source_type or "",
        agent_id=record.agent_id,
        updated_at=getattr(record, "updated_at", None) or getattr(record, "created_at", None),
        workspace_id=record.workspace_id,
        tags=list(record.tags) if record.tags else [],
        metadata=dict(record.metadata) if record.metadata else {},
    )


def _raw_document_to_response(doc: RawDocument) -> KnowledgeRecordResponse:
    """Map a :class:`~metatron.core.models.RawDocument` to the unified shape.

    ``connector_type`` → ``source_type`` (D-P1-04).
    ``tags`` → ``[]`` (no column; D-P1-03).
    ``agent_id`` → ``None``.
    """
    return KnowledgeRecordResponse(
        id=doc.id,
        origin="kb",
        content=doc.content,
        status=doc.status,
        freshness_score=doc.freshness_score,
        source_type=doc.connector_type or "",
        agent_id=None,
        updated_at=doc.updated_at,
        workspace_id=doc.workspace_id,
        tags=[],
        metadata=dict(doc.metadata) if doc.metadata else {},
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/records", response_model=KnowledgeRecordListResponse)
async def list_knowledge_records(
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    raw_doc_service: Annotated[RawDocumentReadService, Depends(get_raw_document_service)],
    origin: KnowledgeOrigin = Query(KnowledgeOrigin.ALL),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> KnowledgeRecordListResponse:
    """Unified, paginated view of agent memory + KB documents.

    ``workspace_id`` is always auth-derived — never accepted from the query
    string or request body (D-P1-01).

    Origin routing:
    - ``origin=agent`` — only ``memory_records``. KB service not called.
    - ``origin=kb`` — only ``raw_documents``. Memory service not called.
    - ``origin=all`` (default) — fan out concurrently. On a single-leg failure,
      returns ``200`` with ``partial=true`` and the other source's rows.  On
      total failure, returns ``503``.

    Pagination under ``origin=all`` is approximate (D-P1-02): each leg returns
    up to ``limit`` rows ordered by its own ``updated_at DESC``; the combined page
    is re-sorted and truncated to ``limit``.  ``total = agent_total + kb_total``.
    """
    workspace_id = get_workspace_id(request)

    # --- Agent-only path ---
    if origin == KnowledgeOrigin.AGENT:
        try:
            mem_records, mem_total = await asyncio.gather(
                memory_service.list_records(
                    workspace_id,
                    limit=limit,
                    offset=offset,
                ),
                memory_service.pg_store.count_records(workspace_id),
            )
        except Exception as exc:
            logger.warning(
                "route.knowledge.agent_leg_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            raise HTTPException(status_code=503, detail="knowledge sources unavailable") from exc

        responses = [_memory_record_to_response(r) for r in mem_records]
        return KnowledgeRecordListResponse(
            records=responses,
            count=len(responses),
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < mem_total,
        )

    # --- KB-only path ---
    if origin == KnowledgeOrigin.KB:
        try:
            kb_records, kb_total = await raw_doc_service.list_records(limit=limit, offset=offset)
        except Exception as exc:
            logger.warning(
                "route.knowledge.kb_leg_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            raise HTTPException(status_code=503, detail="knowledge sources unavailable") from exc

        responses = [_raw_document_to_response(d) for d in kb_records]
        return KnowledgeRecordListResponse(
            records=responses,
            count=len(responses),
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < kb_total,
        )

    # --- All (fan-out) path ---
    results = await asyncio.gather(
        _fetch_agent_leg(memory_service, workspace_id, limit=limit, offset=offset),
        _fetch_kb_leg(raw_doc_service, limit=limit, offset=offset),
        return_exceptions=True,
    )

    agent_result = results[0]
    kb_result = results[1]

    partial = False
    failed_sources: list[Literal["agent", "kb"]] = []

    agent_records: list[KnowledgeRecordResponse] = []
    agent_total: int = 0
    kb_records_resp: list[KnowledgeRecordResponse] = []
    kb_total: int = 0

    if isinstance(agent_result, Exception):
        logger.warning(
            "route.knowledge.partial",
            workspace_id=workspace_id,
            failed_source="agent",
            error=str(agent_result),
        )
        partial = True
        failed_sources.append("agent")
    else:
        agent_records, agent_total = agent_result

    if isinstance(kb_result, Exception):
        logger.warning(
            "route.knowledge.partial",
            workspace_id=workspace_id,
            failed_source="kb",
            error=str(kb_result),
        )
        partial = True
        failed_sources.append("kb")
    else:
        kb_records_resp, kb_total = kb_result

    if partial and len(failed_sources) == 2:
        raise HTTPException(status_code=503, detail="knowledge sources unavailable")

    # Merge, re-sort by updated_at DESC (approximate — see D-P1-02), truncate.
    combined = agent_records + kb_records_resp
    combined.sort(
        key=lambda r: r.updated_at if r.updated_at else datetime.min,
        reverse=True,
    )
    page = combined[:limit]
    total = agent_total + kb_total

    return KnowledgeRecordListResponse(
        records=page,
        count=len(page),
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
        partial=partial,
        failed_sources=failed_sources,
    )


# ---------------------------------------------------------------------------
# Per-leg fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_agent_leg(
    service: MemoryService,
    workspace_id: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[KnowledgeRecordResponse], int]:
    """Fetch agent memory records and total count concurrently."""
    records, total = await asyncio.gather(
        service.list_records(workspace_id, limit=limit, offset=offset),
        service.pg_store.count_records(workspace_id),
    )
    return [_memory_record_to_response(r) for r in records], total


async def _fetch_kb_leg(
    service: RawDocumentReadService,
    *,
    limit: int,
    offset: int,
) -> tuple[list[KnowledgeRecordResponse], int]:
    """Fetch KB raw_documents and total count concurrently."""
    raw_docs, total = await service.list_records(limit=limit, offset=offset)
    return [_raw_document_to_response(d) for d in raw_docs], total
