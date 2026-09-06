"""MCP tool: metronix_source_sync — trigger a background sync for a source."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp

logger = structlog.get_logger()

# Hold references so fire-and-forget sync tasks are not garbage-collected.
_SYNC_TASKS: set[asyncio.Task[None]] = set()

_SCAFFOLD_CONNECTORS = frozenset({"slack_history", "files"})


@mcp.tool(
    description=(
        "Trigger a sync for a data source. The sync runs in the BACKGROUND and "
        "may take up to ~1 hour for large sources; this tool returns immediately.\n\n"
        "**Parameters:**\n"
        "- connection_id: the source to sync (required)\n"
        "- workspace_id: target workspace (optional; uses the server default)\n"
        "- force_full: ignore the incremental watermark and refetch everything\n\n"
        "**Returns:** {status: 'sync_started', sync_id, connection_id, "
        "connector_type}. Poll metronix_source_list to observe completion "
        "(status -> active/error, last_synced_at, error_message). Only working "
        "connectors (confluence/jira/notion/github/gdrive — google_drive also "
        "accepted as an alias for gdrive when creating a source) can sync; "
        "channels and unimplemented connectors are rejected."
    ),
)
async def metronix_source_sync(
    connection_id: str,
    workspace_id: str | None = None,
    force_full: bool = False,
) -> dict[str, Any]:
    """Start a background sync for a data-source connection."""
    try:
        from metronix.connectors.connection_sync import (
            release_unstarted_sync_claim,
            run_connection_sync,
        )
        from metronix.connectors.schemas import CONNECTOR_SCHEMAS
        from metronix.mcp.server import get_activity_bus
        from metronix.mcp.tools._source_deps import resolve
        from metronix.mcp.tools.models import SourceSyncResponse

        ws_id, store, fernet_key = resolve(workspace_id)
        conn = await store.get_connection_decrypted(connection_id, fernet_key)
        if conn is None or conn["workspace_id"] != ws_id:
            raise ValueError("Connection not found")

        connector_type = conn["connector_type"]
        schema = CONNECTOR_SCHEMAS.get(connector_type)
        if not schema or schema.category != "connector":
            raise ValueError("Sync is only available for connectors, not channels")
        if connector_type in _SCAFFOLD_CONNECTORS:
            raise ValueError(
                f"Connector '{connector_type}' is not implemented yet — sync would "
                "fail. Working connectors: confluence, jira, notion, github, gdrive."
            )
        if not conn.get("enabled", True):
            raise ValueError("Connection is disabled")
        # Duplicate-sync guard — an atomic claim, not a check.
        # claim_connection_for_sync is a single conditional
        # UPDATE ... SET status='syncing', sync_claim_id=:sync_id
        # WHERE status != 'syncing': of two racing callers the second
        # re-evaluates the predicate against the winner's committed row and
        # loses, so exactly one request gets past here (#425). Replaces the old
        # read-conn['status']-then-update_connection_status guard, which was a
        # non-atomic check.
        #
        # Gates on status != 'syncing' alone — no time-based reclaim. sync_logs
        # has no heartbeat, so elapsed time cannot tell a healthy long sync (up
        # to ~1h per this tool's own description) from a dead one; reclaiming by
        # age let a retry preempt a still-running task and corrupt connection
        # state when the original later finished (#425 round 1 review). A
        # genuinely killed/hung task is recovered at the next API restart by
        # recover_interrupted_syncs, not here (#401).
        sync_id = f"sync_{uuid.uuid4().hex[:12]}"
        if not await store.claim_connection_for_sync(connection_id, sync_id):
            if not await store.has_running_sync(connection_id):
                # Diagnostic only — does not change the block decision.
                logger.warning(
                    "source_sync.guard.suspected_orphaned_claim",
                    connection_id=connection_id,
                )
            raise ValueError("Sync already in progress for this connection")

        spawned = False
        created_sync_id: str | None = None
        try:
            # Non-fatal: sync still runs, we just lose the pre-inserted log row.
            try:
                await store.create_sync_log(
                    sync_id=sync_id,
                    workspace_id=ws_id,
                    connection_id=connection_id,
                    connector_type=connector_type,
                    trigger="mcp",
                )
                created_sync_id = sync_id
            except Exception:
                logger.warning(
                    "source_sync.create_log.failed", connection_id=connection_id, exc_info=True
                )

            last_synced_iso = conn.get("last_synced_at")
            last_synced_dt: datetime | None = None
            if last_synced_iso:
                try:
                    last_synced_dt = datetime.fromisoformat(last_synced_iso)
                except (ValueError, TypeError):
                    last_synced_dt = None

            # Wire the EventBus the same way the memory tools do (mcp/server.py):
            # when /mcp is mounted on the FastAPI app, this returns the plugin
            # manager's bus, so SYNC_COMPLETED fires (graph-cache invalidation +
            # plugin subscribers), matching the REST path. In standalone stdio/http
            # transport it returns None and emission is a graceful no-op.
            task = asyncio.create_task(
                run_connection_sync(
                    sync_id=sync_id,
                    connection_id=connection_id,
                    connector_type=connector_type,
                    config=conn["config"],
                    workspace_id=ws_id,
                    store=store,
                    event_bus=get_activity_bus(),
                    force_full=force_full,
                    last_synced_at=last_synced_dt,
                )
            )
            _SYNC_TASKS.add(task)
            task.add_done_callback(_SYNC_TASKS.discard)
            spawned = True
        finally:
            if not spawned:
                await release_unstarted_sync_claim(
                    store,
                    connection_id,
                    claim_id=sync_id,
                    sync_id=created_sync_id,
                    message="Sync could not start. Please retry.",
                )

        return SourceSyncResponse(
            status="sync_started",
            sync_id=sync_id,
            connection_id=connection_id,
            connector_type=connector_type,
        ).model_dump()
    except Exception as e:
        return {"error": handle_tool_error("metronix_source_sync", e).to_dict()}
