"""Admin API endpoints — /api/v1/admin.

Migrated from PoC metatron/api_admin.py.
Provides cleanup and system status operations.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from metatron.storage.cleanup import (
    ALLOW_CLEANUP,
    CleanupError,
    cleanup_all,
    cleanup_workspace,
    get_cleanup_preview,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


class CleanupPreviewResponse(BaseModel):
    cleanup_allowed: bool
    qdrant: dict[str, Any]
    memgraph: dict[str, Any]


class CleanupResponse(BaseModel):
    status: str
    qdrant: Optional[dict[str, Any]] = None
    memgraph: Optional[dict[str, Any]] = None
    workspace_id: Optional[str] = None


@router.get("/cleanup/preview", response_model=CleanupPreviewResponse)
def preview_cleanup() -> CleanupPreviewResponse:
    """Preview what data would be deleted (safe, read-only)."""
    preview = get_cleanup_preview()
    return CleanupPreviewResponse(**preview)


@router.delete("/cleanup/workspace/{workspace_id}", response_model=CleanupResponse)
def cleanup_workspace_endpoint(
    workspace_id: str,
    x_confirm_cleanup: Optional[str] = Header(None),
) -> CleanupResponse:
    """Delete all data for a specific workspace.

    Requires ALLOW_CLEANUP=true and X-Confirm-Cleanup: yes header.
    """
    if x_confirm_cleanup != "yes":
        raise HTTPException(status_code=400, detail="Requires header 'X-Confirm-Cleanup: yes'")
    try:
        result = cleanup_workspace(workspace_id, confirm=True)
        return CleanupResponse(**result)
    except CleanupError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("admin.cleanup.workspace.error", workspace_id=workspace_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cleanup/all", response_model=CleanupResponse)
def cleanup_all_endpoint(
    x_confirm_cleanup: Optional[str] = Header(None),
) -> CleanupResponse:
    """Delete ALL data from ALL databases.

    Requires ALLOW_CLEANUP=true and X-Confirm-Cleanup: DELETE-ALL-DATA header.
    """
    if x_confirm_cleanup != "DELETE-ALL-DATA":
        raise HTTPException(status_code=400, detail="Requires header 'X-Confirm-Cleanup: DELETE-ALL-DATA'")
    try:
        result = cleanup_all(confirm=True)
        return CleanupResponse(**result)
    except CleanupError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("admin.cleanup.all.error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def admin_status() -> dict[str, Any]:
    """Get admin/system status."""
    status: dict[str, Any] = {"cleanup_allowed": ALLOW_CLEANUP, "databases": {}}

    try:
        from metatron.storage.cleanup import list_qdrant_collections
        collections = list_qdrant_collections()
        status["databases"]["qdrant"] = {"status": "connected", "collections_count": len(collections)}
    except Exception as e:
        status["databases"]["qdrant"] = {"status": "error", "error": str(e)}

    try:
        from metatron.storage.memgraph import get_memgraph_driver
        driver = get_memgraph_driver()
        with driver.session() as session:
            session.run("RETURN 1 AS ok").single()
        status["databases"]["memgraph"] = {"status": "connected"}
    except Exception as e:
        status["databases"]["memgraph"] = {"status": "error", "error": str(e)}

    return status
