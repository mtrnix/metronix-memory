"""Dashboard sync and ingestion endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from metronix.workspaces.models import Workspace

from .overview import get_valid_workspace

router = APIRouter()


class SyncHistoryItem(BaseModel):
    """Single sync history entry."""

    id: str
    connection_id: str | None
    connector_type: str
    title: str
    started: datetime
    duration_ms: float
    documents_fetched: int
    documents_new: int
    documents_updated: int
    documents_skipped: int
    qdrant_chunks: int
    errors: list[str]
    status: Literal["success", "partial", "failed", "running"]


class SyncHistoryResponse(BaseModel):
    """Sync history response."""

    items: list[SyncHistoryItem]


@router.get("/sync-history", response_model=SyncHistoryResponse)
async def get_sync_history(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
    limit: int = Query(default=10, ge=1, le=100),
    connection_id: str | None = Query(default=None),
) -> SyncHistoryResponse:
    """Get sync history for dashboard. Optionally filter by connection."""
    from metronix.storage.dashboard_queries import get_sync_history_data

    items = await asyncio.to_thread(
        get_sync_history_data,
        workspace.workspace_id,
        limit,
        connection_id,
    )

    return SyncHistoryResponse(items=items)


class IngestionErrorItem(BaseModel):
    """Single ingestion error entry."""

    source: str
    record: str
    error: str
    time: datetime
    severity: Literal["critical", "warning", "info"]


class IngestionErrorsResponse(BaseModel):
    """Ingestion errors response."""

    total: int
    items: list[IngestionErrorItem]


@router.get("/ingestion-errors", response_model=IngestionErrorsResponse)
async def get_ingestion_errors(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
    limit: int = Query(default=20, ge=1, le=100),
) -> IngestionErrorsResponse:
    """Get ingestion errors for dashboard.

    Args:
        workspace: Validated workspace from dependency.
        limit: Maximum number of error records (default: 20, max: 100).

    Returns:
        Ingestion errors with total count and items.
    """
    from metronix.storage.dashboard_queries import get_ingestion_errors_data

    total, items = await asyncio.to_thread(
        get_ingestion_errors_data,
        workspace.workspace_id,
        limit,
    )

    return IngestionErrorsResponse(total=total, items=items)
