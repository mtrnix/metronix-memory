"""RAG debug trace read API — /api/v1/traces.

Read-only viewer surface for persisted RAG debug traces. NOT gated by
``METATRON_RAG_TRACE_ENABLED`` — historical traces stay readable even after
capture is turned off. Workspace-scoped: a trace id from another workspace 404s.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID  # noqa: TC003 — runtime import: FastAPI resolves the path-param annotation

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from metatron.api.dependencies import resolve_workspace_id
from metatron.auth.dependencies import require_viewer
from metatron.core.models import User  # noqa: TC001 — FastAPI Annotated DI needs runtime import

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/traces", tags=["traces"])


class RagTraceListItem(BaseModel):
    trace_id: str
    created_at: str | None
    query: str
    source: str | None
    total_ms: float


class RagTraceListResponse(BaseModel):
    traces: list[RagTraceListItem]
    count: int
    limit: int
    offset: int


@router.get("/{trace_id}")
async def get_trace(
    trace_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
) -> dict[str, Any]:
    """Fetch one full trace JSONB. 404 if missing or in another workspace.

    ``trace_id`` is typed as ``UUID`` so malformed ids return 422 (not a 500 from
    a PG ``invalid input syntax for type uuid``).
    """
    workspace_id = resolve_workspace_id(request)
    from metatron.storage.pg_connection import get_rag_trace_sync

    trace = await asyncio.to_thread(get_rag_trace_sync, workspace_id, str(trace_id))
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace


@router.get("", response_model=RagTraceListResponse)
async def list_traces(
    request: Request,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    limit: int = Query(20, ge=1, le=100),  # noqa: B008
    offset: int = Query(0, ge=0, le=10000),  # noqa: B008
) -> RagTraceListResponse:
    """List recent traces for the workspace (newest-first), lightweight rows."""
    workspace_id = resolve_workspace_id(request)
    from metatron.storage.pg_connection import list_rag_traces_sync

    rows = await asyncio.to_thread(list_rag_traces_sync, workspace_id, limit, offset)
    return RagTraceListResponse(
        traces=[RagTraceListItem(**r) for r in rows],
        count=len(rows),
        limit=limit,
        offset=offset,
    )
