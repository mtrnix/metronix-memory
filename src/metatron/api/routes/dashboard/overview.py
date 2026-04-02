"""Dashboard overview and analytics endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from metatron.workspaces import get_workspace_manager
from metatron.workspaces.models import Workspace

logger = structlog.get_logger()

router = APIRouter()


# Dependency for workspace validation
async def get_valid_workspace(workspace_id: str) -> Workspace:
    """Validate workspace exists and return it.

    Args:
        workspace_id: Workspace ID to validate.

    Returns:
        Workspace object.

    Raises:
        HTTPException: 404 if workspace not found.
    """
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found",
        )
    return workspace


class OverviewKPIResponse(BaseModel):
    """Overview KPI metrics for dashboard."""

    documents: int
    jira_issues: int
    active_connectors: int
    last_upload: datetime | None


@router.get("/overview", response_model=OverviewKPIResponse)
async def get_overview_kpi(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
) -> OverviewKPIResponse:
    """Get overview KPI metrics for dashboard.

    Args:
        workspace: Validated workspace from dependency.

    Returns:
        Overview metrics: documents, jira_issues, active_connectors, last_upload.
    """
    from metatron.storage.dashboard_queries import get_overview_stats

    stats = await asyncio.to_thread(get_overview_stats, workspace.workspace_id)

    return OverviewKPIResponse(
        documents=stats["documents"],
        jira_issues=stats["jira_issues"],
        active_connectors=stats["active_connectors"],
        last_upload=stats["last_upload"],
    )


class QueryTrendResponse(BaseModel):
    """Query trend response."""

    labels: list[str]
    values: list[int]


@router.get("/query-trend", response_model=QueryTrendResponse)
async def get_query_trend(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
    days: int = Query(default=30, ge=1, le=365),
) -> QueryTrendResponse:
    """Get query trend for dashboard.

    Args:
        workspace: Validated workspace from dependency.
        days: Number of days to look back (default: 30, max: 365).

    Returns:
        Query trend with date labels and query counts.
    """
    from metatron.storage.dashboard_queries import get_query_trend_data

    labels, values = await asyncio.to_thread(
        get_query_trend_data,
        workspace.workspace_id,
        days,
    )

    return QueryTrendResponse(labels=labels, values=values)
