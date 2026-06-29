"""Admin API endpoints — /api/v1/admin.

Migrated from PoC metronix/api_admin.py.
Provides cleanup and system status operations.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from metronix.core.config import Settings
from metronix.storage.cleanup import (
    ALLOW_CLEANUP,
    CleanupError,
    cleanup_all,
    cleanup_workspace,
    get_cleanup_preview,
)
from metronix.storage.postgres import PostgresStore

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


class CleanupPreviewResponse(BaseModel):
    cleanup_allowed: bool
    qdrant: dict[str, Any]
    memgraph: dict[str, Any]  # deprecated, use neo4j
    neo4j: dict[str, Any] | None = None


class CleanupResponse(BaseModel):
    status: str
    qdrant: dict[str, Any] | None = None
    memgraph: dict[str, Any] | None = None  # deprecated, use neo4j
    neo4j: dict[str, Any] | None = None
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
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        logger.error("admin.cleanup.workspace.error", workspace_id=workspace_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


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
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        logger.error("admin.cleanup.all.error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


class ReindexResponse(BaseModel):
    status: str
    docs_reset: int
    graph_cleared: bool
    sync_state_cleared: bool


@router.post("/reindex", response_model=ReindexResponse)
async def trigger_reindex(
    request: Request,
    x_confirm_reindex: str | None = Header(None),
) -> ReindexResponse:
    """Trigger full reindex: reset sync flags and clear Neo4j graph.

    **GLOBAL operation — affects EVERY workspace in this deployment.** There
    is no per-workspace scoping; ``connections.last_synced_at`` is NULL'd for
    all rows and ``raw_documents`` qdrant/graph flags are reset across the
    whole table. On a multi-tenant deployment this triggers a re-embed and
    re-graph storm on every tenant simultaneously. The ``X-Confirm-Reindex:
    yes`` header is the only safety net — operators must understand the
    blast radius. Per-workspace reindex is a separate follow-up.

    Does NOT require ALLOW_CLEANUP. After calling this, trigger sync from UI
    to re-ingest all documents with current settings (e.g. SPLADE vectors).

    Steps:
    1. Reset PG sync state in a single transaction:
       - connections.last_synced_at = NULL (forces full fetch on next sync)
       - raw_documents.qdrant_synced = false
       - raw_documents.graph_synced = false
    1b. Best-effort: clear legacy file-based SyncState (rolling-deploy guard).
    2. Clear Neo4j graph (DETACH DELETE all nodes).

    Requires header X-Confirm-Reindex: yes
    """
    if x_confirm_reindex != "yes":
        raise HTTPException(
            status_code=400,
            detail="Requires header 'X-Confirm-Reindex: yes'",
        )

    docs_reset = 0
    graph_cleared = False
    sync_state_cleared = False

    # 1. Reset PG sync state — clear connections.last_synced_at AND
    # raw_documents.{qdrant,graph}_synced flags in a single transaction so
    # we use one connection from the pool (MTRNIX-332).
    # Next sync starts from since=None (full fetch).
    store: PostgresStore | None = getattr(request.app.state, "postgres", None)
    if store is None:
        settings: Settings = request.app.state.settings
        store = PostgresStore(settings.postgres_dsn)
        request.app.state.postgres = store
    try:
        from sqlalchemy import text

        async with store._engine.begin() as conn:
            await conn.execute(text("UPDATE connections SET last_synced_at = NULL"))
            r = await conn.execute(
                text(
                    "UPDATE raw_documents "
                    "SET qdrant_synced = false, qdrant_synced_at = NULL, "
                    "    graph_synced = false, graph_synced_at = NULL"
                )
            )
            docs_reset = r.rowcount
        sync_state_cleared = True
        logger.info("admin.reindex.pg_reset_done", docs_reset=docs_reset)
    except Exception as e:
        logger.warning("admin.reindex.pg_reset_error", error=str(e))

    # 1b. Best-effort: clear legacy file-based SyncState (no-op if file is
    # not present or already empty; survives mid-rollout deployments).
    # TODO(MTRNIX-332 follow-up): drop after one release cycle along with
    # sync_state.py + test_incremental_sync.py.
    try:
        from metronix.connectors.sync_state import SyncState

        ss = SyncState()
        for key in list(ss._state.keys()):
            parts = key.split(":", 1)
            if len(parts) == 2:
                ss.clear(parts[0], parts[1])
        logger.info("admin.reindex.legacy_sync_state_cleared")
    except Exception as e:
        logger.warning("admin.reindex.legacy_sync_state_error", error=str(e))

    # 2. Clear Neo4j graph
    try:
        from metronix.storage.neo4j_graph import get_graph_driver

        driver = get_graph_driver()
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        graph_cleared = True
        logger.info("admin.reindex.graph_cleared")
    except Exception as e:
        logger.warning("admin.reindex.graph_error", error=str(e))

    return ReindexResponse(
        status="reindex_ready",
        docs_reset=docs_reset,
        graph_cleared=graph_cleared,
        sync_state_cleared=sync_state_cleared,
    )


@router.get("/status")
def admin_status() -> dict[str, Any]:
    """Get admin/system status."""
    status: dict[str, Any] = {"cleanup_allowed": ALLOW_CLEANUP, "databases": {}}

    try:
        from metronix.storage.cleanup import list_qdrant_collections

        collections = list_qdrant_collections()
        status["databases"]["qdrant"] = {
            "status": "connected",
            "collections_count": len(collections),
        }
    except Exception as e:
        status["databases"]["qdrant"] = {"status": "error", "error": str(e)}

    try:
        from metronix.storage.neo4j_graph import get_graph_driver

        driver = get_graph_driver()
        with driver.session() as session:
            session.run("RETURN 1 AS ok").single()
        status["databases"]["neo4j"] = {"status": "connected"}
    except Exception as e:
        status["databases"]["neo4j"] = {"status": "error", "error": str(e)}

    return status
