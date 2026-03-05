"""Dashboard sync and ingestion endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .overview import get_valid_workspace
from metatron.workspaces.models import Workspace

router = APIRouter()


class SyncHistoryItem(BaseModel):
    """Single sync history entry."""

    id: str
    source: str
    title: str
    started: datetime
    duration_ms: float
    records: int
    status: Literal["success", "partial", "failed"]


class SyncHistoryResponse(BaseModel):
    """Sync history response."""

    items: list[SyncHistoryItem]


@router.get("/sync-history", response_model=SyncHistoryResponse)
async def get_sync_history(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
    limit: int = Query(default=10, ge=1, le=100),
) -> SyncHistoryResponse:
    """Get sync history for dashboard.

    Args:
        workspace: Validated workspace from dependency.
        limit: Maximum number of records (default: 10, max: 100).

    Returns:
        Sync history items.
    """
    from metatron.storage.dashboard_queries import get_sync_history_data
    
    items = await asyncio.to_thread(
        get_sync_history_data,
        workspace.workspace_id,
        limit,
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
    from metatron.storage.dashboard_queries import get_ingestion_errors_data
    
    total, items = await asyncio.to_thread(
        get_ingestion_errors_data,
        workspace.workspace_id,
        limit,
    )
    
    return IngestionErrorsResponse(total=total, items=items)
