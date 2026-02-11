"""Sync status and logs API — /api/v1/sync."""

from __future__ import annotations

import structlog
from fastapi import APIRouter

logger = structlog.get_logger()

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
async def sync_status(workspace_id: str) -> dict[str, object]:
    """Get sync status for all connections in a workspace.

    Returns last sync time, status, and error counts per connection.
    """
    logger.info("api.sync.status", workspace_id=workspace_id)
    # TODO: implement
    # 1. Fetch all connections for workspace
    # 2. For each: last_synced_at, status, error count from sync_logs
    return {"workspace_id": workspace_id, "connections": []}


@router.get("/logs")
async def sync_logs(
    workspace_id: str, connection_id: str | None = None, limit: int = 50
) -> list[dict[str, object]]:
    """Get recent sync log entries.

    Args:
        workspace_id: Workspace filter.
        connection_id: Optional connection filter.
        limit: Max entries to return (default 50).
    """
    logger.info(
        "api.sync.logs",
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    # TODO: implement
    # SELECT * FROM sync_logs WHERE workspace_id = $1
    # AND ($2 IS NULL OR connection_id = $2)
    # ORDER BY created_at DESC LIMIT $3
    return []
