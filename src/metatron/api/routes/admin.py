"""Admin API endpoints — /api/v1/admin.

Migrated from PoC metatron/api_admin.py.
Provides cleanup and system status operations.
"""

from __future__ import annotations

from typing import Any

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
    qdrant: dict[str, Any] | None = None
    memgraph: dict[str, Any] | None = None
    workspace_id: str | None = None


@router.get("/cleanup/preview", response_model=CleanupPreviewResponse)
def preview_cleanup() -> CleanupPreviewResponse:
    """Preview what data would be deleted (safe, read-only)."""
    preview = get_cleanup_preview()
    return CleanupPreviewResponse(**preview)


@router.delete("/cleanup/workspace/{workspace_id}", response_model=CleanupResponse)
def cleanup_workspace_endpoint(
    workspace_id: str,
    x_confirm_cleanup: str | None = Header(None),
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
    x_confirm_cleanup: str | None = Header(None),
) -> CleanupResponse:
    """Delete ALL data from ALL databases.

    Requires ALLOW_CLEANUP=true and X-Confirm-Cleanup: DELETE-ALL-DATA header.
    """
    if x_confirm_cleanup != "DELETE-ALL-DATA":
        raise HTTPException(
            status_code=400, detail="Requires header 'X-Confirm-Cleanup: DELETE-ALL-DATA'"
        )
    try:
        result = cleanup_all(confirm=True)
        return CleanupResponse(**result)
    except CleanupError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("admin.cleanup.all.error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class ReindexResponse(BaseModel):
    status: str
    docs_reset: int
    memgraph_cleared: bool
    sync_state_cleared: bool


@router.post("/reindex", response_model=ReindexResponse)
async def trigger_reindex(
    x_confirm_reindex: str | None = Header(None),
) -> ReindexResponse:
    """Trigger full reindex: reset sync flags and clear Memgraph.

    Does NOT require ALLOW_CLEANUP. After calling this, trigger sync from UI
    to re-ingest all documents with current settings (e.g. SPLADE vectors).

    Steps:
    1. Reset sync state (forces full fetch from connectors)
    2. Reset qdrant_synced=false for all raw_documents
    3. Reset graph_synced=false for all raw_documents
    4. Clear Memgraph (DETACH DELETE all nodes)

    Requires header X-Confirm-Reindex: yes
    """
    if x_confirm_reindex != "yes":
        raise HTTPException(
            status_code=400,
            detail="Requires header 'X-Confirm-Reindex: yes'",
        )

    docs_reset = 0
    memgraph_cleared = False
    sync_state_cleared = False

    # 1. Reset sync state
    try:
        from metatron.connectors.sync_state import SyncState

        ss = SyncState()
        # Clear all known workspace+connector combos
        for key in list(ss._state.keys()):
            parts = key.split(":", 1)
            if len(parts) == 2:
                ss.clear(parts[0], parts[1])
        sync_state_cleared = True
        logger.info("admin.reindex.sync_state_cleared")
    except Exception as e:
        logger.warning("admin.reindex.sync_state_error", error=str(e))

    # 2. Reset qdrant_synced + graph_synced in raw_documents
    try:
        from metatron.core.config import Settings
        from metatron.storage.postgres import PostgresStore
        from sqlalchemy import text

        s = Settings()
        store = PostgresStore(s.postgres_dsn)
        async with store._engine.begin() as conn:
            r = await conn.execute(
                text(
                    "UPDATE raw_documents "
                    "SET qdrant_synced = false, qdrant_synced_at = NULL, "
                    "    graph_synced = false, graph_synced_at = NULL"
                )
            )
            docs_reset = r.rowcount
        await store.close()
        logger.info("admin.reindex.docs_reset", count=docs_reset)
    except Exception as e:
        logger.warning("admin.reindex.docs_reset_error", error=str(e))

    # 3. Clear Memgraph
    try:
        from metatron.storage.memgraph import get_memgraph_driver

        driver = get_memgraph_driver()
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        memgraph_cleared = True
        logger.info("admin.reindex.memgraph_cleared")
    except Exception as e:
        logger.warning("admin.reindex.memgraph_error", error=str(e))

    return ReindexResponse(
        status="reindex_ready",
        docs_reset=docs_reset,
        memgraph_cleared=memgraph_cleared,
        sync_state_cleared=sync_state_cleared,
    )


@router.get("/status")
def admin_status() -> dict[str, Any]:
    """Get admin/system status."""
    status: dict[str, Any] = {"cleanup_allowed": ALLOW_CLEANUP, "databases": {}}

    try:
        from metatron.storage.cleanup import list_qdrant_collections

        collections = list_qdrant_collections()
        status["databases"]["qdrant"] = {
            "status": "connected",
            "collections_count": len(collections),
        }
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
