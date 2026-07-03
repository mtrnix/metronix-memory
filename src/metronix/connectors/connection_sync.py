"""Connection-sync orchestration (L3).

Extracted from ``api/routes/connections.py`` so MCP tools (also L3) can trigger
a DB-connection sync without importing upward into the API layer (L6).
Behaviour is unchanged; the REST route delegates here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text as sa_text

from metronix.connectors.registry import ConnectorRegistry, register_builtins
from metronix.core.events import SYNC_COMPLETED, EventBus
from metronix.core.interfaces import ConnectorInterface, CursorConnector
from metronix.core.models import Connection

if TYPE_CHECKING:
    from datetime import datetime

    from metronix.storage.postgres import PostgresStore

logger = structlog.get_logger()


async def _load_cursor(store: PostgresStore, connection_id: str, connector: object) -> None:
    """Load a CursorConnector's persisted cursor; degrade to None on any error."""
    if not isinstance(connector, CursorConnector):
        return
    cursor: str | None = None
    try:
        state = await store.get_connector_state(connection_id)
        cursor = (state or {}).get("page_token")
    except Exception as e:  # noqa: BLE001 — degrade to full sweep, never crash sync
        logger.warning("sync.cursor_load_failed", connection_id=connection_id, error=str(e))
    connector.load_cursor(cursor)


async def _persist_cursor(
    store: PostgresStore, connection_id: str, connector: object, status: str
) -> None:
    """Persist a CursorConnector's next cursor — only on a fully successful sync."""
    if status != "success" or not isinstance(connector, CursorConnector):
        return
    token = connector.take_cursor()
    if not token:
        return
    try:
        await store.set_connector_state(connection_id, {"page_token": token})
    except Exception as e:  # noqa: BLE001 — best-effort; a lost token retries next sync
        logger.warning("sync.cursor_save_failed", connection_id=connection_id, error=str(e))


# Module-level registry instance
_registry: ConnectorRegistry | None = None


def get_registry() -> ConnectorRegistry:
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry()
        register_builtins(_registry)
    return _registry


def sanitize_error(error: str) -> str:
    """Remove sensitive info from error messages before storing/returning."""
    # Mask URLs with credentials
    error = re.sub(r"://[^:]+:[^@]+@", "://***:***@", error)
    # Mask file paths
    error = re.sub(r"/Users/[^\s]+", "/...", error)
    error = re.sub(r"/home/[^\s]+", "/...", error)
    # Mask tokens/keys that might appear in errors
    error = re.sub(
        r"(token|key|secret|password)[\s=:]+\S+",
        r"\1=***",
        error,
        flags=re.IGNORECASE,
    )
    # Truncate to reasonable length
    if len(error) > 500:
        error = error[:500] + "..."
    return error


async def ensure_workspace_exists(store: PostgresStore, workspace_id: str) -> None:
    """Ensure the workspace row exists in PostgreSQL (FK target for connections).

    The WorkspaceManager creates it lazily on first use, but connections may
    be created before any workspace route is hit.  This upsert guarantees the
    FK target is present.
    """
    async with store._engine.begin() as conn:
        await conn.execute(
            sa_text("""
                INSERT INTO workspaces (id, name, slug, created_at)
                VALUES (:id, :name, :slug, NOW())
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": workspace_id,
                "name": workspace_id,
                "slug": workspace_id.lower(),
            },
        )


async def run_connection_sync(
    sync_id: str,
    connection_id: str,
    connector_type: str,
    config: dict[str, Any],
    workspace_id: str,
    store: PostgresStore,
    event_bus: EventBus | None = None,
    force_full: bool = False,
    last_synced_at: datetime | None = None,
) -> None:
    """Run sync for a DB-based connection. Async background task.

    Expects a `sync_logs` row with id=sync_id already inserted by
    `trigger_sync` with status='running'. Updates that row on
    completion, failure, or exception.

    ``last_synced_at`` is the cursor for incremental fetch — read from
    ``connections.last_synced_at`` by the caller. ``None`` means "no
    prior sync" (fresh connection) and the connector performs a full
    fetch. After successful sync, the cursor is advanced by
    ``update_connection_status`` in the finally block.

    ``force_full=True`` ignores ``last_synced_at`` entirely and performs
    a full refetch. The cursor is still stamped on success — this is a
    one-off reset, not a permanent mode flip.
    """
    import time
    from datetime import UTC, datetime

    from metronix.ingestion.pipeline import ingest_documents

    start_time = time.perf_counter()
    # Capture the wall-clock instant BEFORE the remote fetch. The cursor must
    # be stamped with this value (not datetime.now() in the finally block) so
    # any source-side update that happens DURING fetch+ingest+graph is still
    # captured by the next sync. Otherwise, a long sync (Confluence/Jira can
    # take minutes) silently drops every doc whose `updated` falls inside
    # that window (PROJ-332 review B1). Re-fetching one doc next time
    # (content_hash dedup makes it cheap) is strictly better than losing one
    # forever.
    fetch_started_at = datetime.now(UTC)
    status = "failed"
    connector: ConnectorInterface | None = None  # bound in try; used by _persist_cursor in finally
    documents_fetched = 0
    documents_new = 0
    documents_updated = 0
    documents_skipped = 0
    qdrant_chunks = 0
    errors_list: list[str] = []

    logger.info(
        "sync.db_connection.started",
        sync_id=sync_id,
        connection_id=connection_id,
        connector_type=connector_type,
    )
    try:
        registry = get_registry()
        connector = registry.create(connector_type)

        connection_obj = Connection(
            id=connection_id,
            workspace_id=workspace_id,
            connector_type=connector_type,
        )

        await connector.configure(connection_obj, config)
        await _load_cursor(store, connection_id, connector)

        # Incremental cursor from PG (connections.last_synced_at). For a
        # freshly-created connection this is NULL → ``since=None`` → full
        # fetch (correct: nothing has been ingested yet). The cursor is
        # advanced in the finally block via update_connection_status.
        if force_full:
            since = None
            logger.info(
                "sync.force_full",
                sync_id=sync_id,
                connector_type=connector_type,
                workspace_id=workspace_id,
            )
        else:
            since = last_synced_at
        documents = await connector.fetch(workspace_id, since=since)
        documents_fetched = len(documents)

        logger.info(
            "sync.fetched",
            sync_id=sync_id,
            connector_type=connector_type,
            documents=documents_fetched,
            since=since.isoformat() if since else None,
            force_full=force_full,
        )

        # Phase 1: Persist raw documents to PostgreSQL (source of truth)
        upsert_result: dict[str, Any] | None = None
        try:
            upsert_result = await store.upsert_raw_documents(
                workspace_id=workspace_id,
                # Connectors yield core ``Document`` objects; the store accepts
                # them at the raw-document boundary (inherited loose typing).
                documents=documents,  # type: ignore[arg-type]
                connector_type=connector_type,
                connection_id=connection_id,
            )
            logger.info(
                "sync.raw_documents.persisted",
                new=upsert_result["new"],
                updated=upsert_result["updated"],
                unchanged=upsert_result["unchanged"],
            )
        except Exception as e:
            logger.warning("sync.raw_documents.error", error=str(e))

        # Phase 1b: Enqueue KB freshness jobs for changed docs (PROJ-313).
        # Flag-gated; with both freshness flags off this is a zero-Redis no-op.
        # We enqueue per PG raw_document id so the worker can look the row up
        # directly via ``get_raw_document_by_id`` without replaying natural
        # keys.
        if upsert_result and upsert_result.get("changed_source_ids"):
            from metronix.ingestion.freshness.producer import (
                enqueue_raw_document_if_enabled,
            )

            for src_id in upsert_result["changed_source_ids"]:
                try:
                    raw_doc_row = await store.get_raw_document(
                        workspace_id=workspace_id,
                        connector_type=connector_type,
                        source_id=src_id,
                    )
                except Exception:
                    logger.debug(
                        "sync.freshness.lookup_failed",
                        source_id=src_id,
                        exc_info=True,
                    )
                    continue
                if not raw_doc_row:
                    continue
                raw_doc_id = raw_doc_row.get("id") if isinstance(raw_doc_row, dict) else None
                if not raw_doc_id:
                    continue
                # ``content_changed`` is the generic event label for KB
                # upserts (new + updated are not distinguished by the worker
                # today; they go through the same pipeline).
                await enqueue_raw_document_if_enabled(
                    workspace_id=workspace_id,
                    raw_document_id=raw_doc_id,
                    event_type="content_changed",
                    payload={"connector_type": connector_type, "source_id": src_id},
                )

        # Phase 2: Ingest into Qdrant (only new/updated docs, skip unchanged)
        if upsert_result and upsert_result.get("changed_source_ids"):
            changed_ids = set(upsert_result["changed_source_ids"])
            docs_to_ingest = [d for d in documents if d.source_id in changed_ids]
            logger.info(
                "sync.filtering_unchanged",
                total=len(documents),
                changed=len(docs_to_ingest),
                skipped=len(documents) - len(docs_to_ingest),
            )
        else:
            docs_to_ingest = documents

        if docs_to_ingest:
            result = await ingest_documents(
                docs_to_ingest,
                workspace_id,
                connector_type,
                source_role=connector.source_role,
                skip_graph=True,
            )
            documents_new = result.documents_new
            documents_updated = result.documents_updated
            documents_skipped = result.documents_skipped
            qdrant_chunks = result.documents_new + result.documents_updated

            if result.errors:
                errors_list = [sanitize_error(str(e)) for e in result.errors[:10]]
                status = "partial" if result.documents_new > 0 else "failed"
            else:
                status = "success"

            # Phase 3: Mark Qdrant sync status in raw_documents
            try:
                all_source_ids = [d.source_id for d in documents if d.source_id]
                if all_source_ids:
                    await store.mark_documents_synced_by_source(
                        workspace_id=workspace_id,
                        connector_type=connector_type,
                        source_ids=all_source_ids,
                        target="qdrant",
                    )
            except Exception as e:
                logger.warning("sync.mark_synced.error", error=str(e))
        else:
            status = "success"

        # Phase 4: Graph extraction from PG (always runs — picks up pending docs)
        try:
            from metronix.ingestion.pipeline import process_all_unsynced_graphs

            graph_result = await process_all_unsynced_graphs(workspace_id, store)
            logger.info(
                "sync.graph_processing.done",
                ok=graph_result["ok"],
                errors=graph_result["errors"],
            )
        except Exception as e:
            logger.warning("sync.graph_processing.error", error=str(e))

    except Exception as e:
        logger.error(
            "sync.db_connection.failed",
            sync_id=sync_id,
            connection_id=connection_id,
            error=str(e),
        )
        errors_list = [sanitize_error(str(e))]
        status = "failed"

    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        final_conn_status = "active" if status == "success" else "error"
        error_msg = "; ".join(errors_list) if errors_list else None

        # Update sync_logs row (centralized helper — Task 2)
        try:
            await store.update_sync_log(
                sync_id=sync_id,
                status=status,
                documents_fetched=documents_fetched,
                documents_new=documents_new,
                documents_updated=documents_updated,
                documents_skipped=documents_skipped,
                qdrant_chunks=qdrant_chunks,
                errors=errors_list,
                duration_ms=duration_ms,
            )
            logger.info("sync.logged", sync_id=sync_id, status=status, duration_ms=duration_ms)
        except Exception as e:
            logger.warning("sync.log_failed", sync_id=sync_id, error=str(e))

        # Update connection status. The cursor (last_synced_at) is advanced
        # ONLY on success/partial, and stamped with ``fetch_started_at`` (NOT
        # ``now()``) — see the explanation at the top of this function.
        # Passing ``last_synced_at=None`` means "leave the column unchanged"
        # — see ``update_connection_status`` for the conditional SET clause.
        try:
            await store.update_connection_status(
                connection_id,
                status=final_conn_status,
                error_message=error_msg,
                last_synced_at=(fetch_started_at if status in ("success", "partial") else None),
            )
        except Exception as e:
            logger.warning(
                "sync.status_update_failed",
                connection_id=connection_id,
                error=str(e),
            )

        # Persist the connector's incremental cursor alongside last_synced_at,
        # and ONLY on full success — see _persist_cursor.
        await _persist_cursor(store, connection_id, connector, status)

        # Emit SYNC_COMPLETED for cache invalidation and plugin hooks
        if event_bus is not None:
            try:
                await event_bus.emit(
                    SYNC_COMPLETED,
                    {
                        "sync_id": sync_id,
                        "workspace_id": workspace_id,
                        "connection_id": connection_id,
                        "connector_type": connector_type,
                        "status": status,
                    },
                )
            except Exception as e:
                logger.warning("sync.event_emit.failed", error=str(e))
