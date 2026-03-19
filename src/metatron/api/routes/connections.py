"""Connections CRUD API + sync trigger — /api/v1/connections."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text as sa_text

from metatron.connectors.registry import ConnectorRegistry, register_builtins
from metatron.connectors.schemas import (
    CONNECTOR_SCHEMAS,
    validate_config,
)
from metatron.core.config import Settings
from metatron.core.models import Connection
from metatron.storage.postgres import PostgresStore

logger = structlog.get_logger()

router = APIRouter(prefix="/connections", tags=["connections"])

# Module-level registry instance
_registry: ConnectorRegistry | None = None


def _get_registry() -> ConnectorRegistry:
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry()
        register_builtins(_registry)
    return _registry


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class CreateConnectionRequest(BaseModel):
    """Request body for creating a connection."""

    model_config = ConfigDict(strict=True)

    connector_type: str
    name: str
    config: dict[str, Any]


class UpdateConnectionRequest(BaseModel):
    """Request body for updating a connection."""

    model_config = ConfigDict(strict=True)

    name: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ConnectionResponse(BaseModel):
    """Response body for a connection (config has masked secrets)."""

    id: str
    workspace_id: str
    connector_type: str
    name: str
    config: dict[str, Any]
    status: str
    enabled: bool
    error_message: str | None
    last_synced_at: str | None
    created_at: str | None
    updated_at: str | None


class TestConnectionResponse(BaseModel):
    """Response body for connection test."""

    success: bool
    message: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_workspace_id(
    request: Request,
    workspace_id: str | None = None,
) -> str:
    """Resolve workspace_id: query param > auth token > default.

    The wildcard ``"*"`` means "admin has access to all workspaces" — it is
    NOT a real workspace_id and must never be stored.  When encountered,
    fall back to ``default_workspace_id``.
    """
    if workspace_id and workspace_id != "*":
        return workspace_id
    user = getattr(request.state, "user", {}) or {}
    workspace_ids = user.get("workspace_ids", [])
    if workspace_ids and workspace_ids[0] != "*":
        return workspace_ids[0]
    settings: Settings = request.app.state.settings
    return settings.default_workspace_id


def _get_fernet_key(request: Request) -> str:
    """Get Fernet encryption key from settings."""
    settings: Settings = request.app.state.settings
    if not settings.fernet_key:
        raise HTTPException(
            status_code=500,
            detail="FERNET_KEY not configured. Set the FERNET_KEY env var.",
        )
    return settings.fernet_key


def _get_store(request: Request) -> PostgresStore:
    """Get PostgresStore from app state."""
    store = getattr(request.app.state, "postgres", None)
    if store is None:
        settings: Settings = request.app.state.settings
        store = PostgresStore(settings.postgres_dsn)
        request.app.state.postgres = store
    return store


async def _ensure_workspace_exists(store: PostgresStore, workspace_id: str) -> None:
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


async def _try_start_channel(
    request: Request,
    connection_id: str,
    connector_type: str,
    config: dict[str, Any],
    workspace_id: str,
) -> None:
    """Start a channel bot if ChannelManager is available on app.state.

    Non-fatal — logs warning on failure but never raises.
    """
    channel_manager = getattr(request.app.state, "channel_manager", None)
    if channel_manager is None:
        logger.info(
            "api.connections.channel_start.skipped",
            reason="no channel_manager on app.state",
            connection_id=connection_id,
        )
        return

    try:
        await channel_manager.start_channel(
            connection_id, connector_type, config,
            workspace_id=workspace_id,
        )
        logger.info(
            "api.connections.channel_started",
            connection_id=connection_id,
            connector_type=connector_type,
        )
    except Exception as exc:
        logger.warning(
            "api.connections.channel_start.failed",
            connection_id=connection_id,
            error=_sanitize_error(str(exc)),
        )


# ---------------------------------------------------------------------------
# New CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/schemas/")
async def get_schemas() -> dict[str, Any]:
    """Return all connector schemas for UI form rendering."""
    schemas = {}
    for key, schema in CONNECTOR_SCHEMAS.items():
        schemas[key] = {
            "type": schema.type,
            "label": schema.label,
            "category": schema.category,
            "fields": [asdict(f) for f in schema.fields],
        }
    return {"schemas": schemas}


@router.post("/", status_code=201, response_model=ConnectionResponse)
async def create_connection(
    body: CreateConnectionRequest,
    request: Request,
    workspace_id: str | None = Query(None),
) -> ConnectionResponse:
    """Create a new data source connection.

    Validates the connector type and config, encrypts credentials,
    and stores in PostgreSQL.
    """
    logger.info("api.connections.create", connector_type=body.connector_type)

    if body.connector_type not in CONNECTOR_SCHEMAS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown connector type '{body.connector_type}'. "
                f"Available: {sorted(CONNECTOR_SCHEMAS.keys())}"
            ),
        )

    errors = validate_config(body.connector_type, body.config)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    ws_id = _get_workspace_id(request, workspace_id)
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)

    try:
        await _ensure_workspace_exists(store, ws_id)
        result = await store.create_connection(
            workspace_id=ws_id,
            connector_type=body.connector_type,
            name=body.name,
            config=body.config,
            fernet_key=fernet_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except Exception as e:
        logger.error(
            "api.connections.create.failed",
            connector_type=body.connector_type,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create connection: {_sanitize_error(str(e))}",
        ) from None

    # Auto-start channel if ChannelManager is available
    schema = CONNECTOR_SCHEMAS.get(body.connector_type)
    if schema and schema.category == "channel":
        await _try_start_channel(
            request, result["id"], body.connector_type, body.config, ws_id,
        )

    return ConnectionResponse(**result)


@router.get("/", response_model=dict)
async def list_connections(
    request: Request,
    category: str | None = None,
    workspace_id: str | None = Query(None),
) -> dict[str, Any]:
    """List all connections for the current workspace.

    Optionally filter by category ('connector' or 'channel').
    """
    ws_id = _get_workspace_id(request, workspace_id)
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)

    logger.info("api.connections.list", workspace_id=ws_id)
    connections = await store.list_connections(ws_id, fernet_key)

    if category:
        if category not in ("connector", "channel"):
            raise HTTPException(
                status_code=400,
                detail="category must be 'connector' or 'channel'",
            )
        connections = [
            c for c in connections
            if CONNECTOR_SCHEMAS.get(c["connector_type"], None)
            and CONNECTOR_SCHEMAS[c["connector_type"]].category == category
        ]

    return {"connections": connections}


@router.get(
    "/{connection_id}/",
    response_model=ConnectionResponse,
)
async def get_connection(
    connection_id: str,
    request: Request,
    workspace_id: str | None = Query(None),
) -> ConnectionResponse:
    """Get a single connection by ID with masked secrets."""
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    conn = await store.get_connection(connection_id, fernet_key)
    if conn is None or conn["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    return ConnectionResponse(**conn)


@router.get(
    "/{connection_id}/reveal-secrets/",
    response_model=ConnectionResponse,
)
async def reveal_connection_secrets(
    connection_id: str,
    request: Request,
    workspace_id: str | None = Query(None),
) -> ConnectionResponse:
    """Get a single connection with decrypted secret values.

    Requires editor role or higher.  Returns the same shape as
    ``get_connection`` but with real secret values instead of ``***``.
    """
    settings: Settings = request.app.state.settings
    if settings.auth_enabled:
        user = getattr(request.state, "user", {})
        if user.get("role") not in ("editor", "admin"):
            raise HTTPException(status_code=403, detail="Editor access required")

    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    conn = await store.get_connection_decrypted(connection_id, fernet_key)
    if conn is None or conn["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    logger.info(
        "api.connections.reveal_secrets",
        connection_id=connection_id,
        workspace_id=ws_id,
    )

    return ConnectionResponse(**conn)


@router.put(
    "/{connection_id}/",
    response_model=ConnectionResponse,
)
async def update_connection(
    connection_id: str,
    body: UpdateConnectionRequest,
    request: Request,
    workspace_id: str | None = Query(None),
) -> ConnectionResponse:
    """Update a connection's config, name, or enabled status."""
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    # Verify ownership
    existing = await store.get_connection(connection_id, fernet_key)
    if existing is None or existing["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.config is not None:
        errors = validate_config(
            existing["connector_type"], body.config,
        )
        # Allow masked secrets through validation (they'll be merged)
        from metatron.connectors.schemas import SECRET_MASK
        if errors:
            # Re-check: are all errors for fields that are masked?
            real_errors = []
            for err in errors:
                # Check if the error is for a secret field that has mask
                skip = False
                schema = CONNECTOR_SCHEMAS.get(existing["connector_type"])
                if schema:
                    for f in schema.fields:
                        if (
                            f.label in err
                            and f.type == "secret"
                            and body.config.get(f.name) == SECRET_MASK
                        ):
                            skip = True
                            break
                if not skip:
                    real_errors.append(err)
            if real_errors:
                raise HTTPException(
                    status_code=422, detail="; ".join(real_errors),
                )
        updates["config"] = body.config

    if not updates:
        raise HTTPException(
            status_code=422, detail="No fields to update",
        )

    try:
        result = await store.update_connection(
            connection_id, updates, fernet_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    if result is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    return ConnectionResponse(**result)


@router.delete("/{connection_id}/", status_code=204)
async def delete_connection(
    connection_id: str,
    request: Request,
    workspace_id: str | None = Query(None),
) -> None:
    """Delete a connection and its encrypted credentials."""
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    # Verify ownership
    existing = await store.get_connection(connection_id, fernet_key)
    if existing is None or existing["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Stop channel if running
    channel_manager = getattr(request.app.state, "channel_manager", None)
    if channel_manager is not None:
        await channel_manager.stop_channel(connection_id)

    logger.info("api.connections.delete", connection_id=connection_id)
    await store.delete_connection(connection_id)


@router.post(
    "/{connection_id}/test/",
    response_model=TestConnectionResponse,
)
async def test_connection(
    connection_id: str,
    request: Request,
    workspace_id: str | None = Query(None),
) -> TestConnectionResponse:
    """Test a connection by attempting to configure the connector."""
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    conn = await store.get_connection_decrypted(connection_id, fernet_key)
    if conn is None or conn["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    connector_type = conn["connector_type"]
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    if not schema or schema.category != "connector":
        # Channels don't have a testable configure() flow
        return TestConnectionResponse(
            success=True,
            message=(
                "Connection saved "
                "(test not available for this type)"
            ),
        )

    registry = _get_registry()
    if not registry.is_registered(connector_type):
        return TestConnectionResponse(
            success=True,
            message=(
                "Connection saved "
                "(test not available for this type)"
            ),
        )

    try:
        connector = registry.create(connector_type)
        connection_obj = Connection(
            id=conn["id"],
            workspace_id=conn["workspace_id"],
            connector_type=connector_type,
        )
        await connector.configure(connection_obj, conn["config"])

        # Clear error on success
        await store.update_connection_status(
            connection_id, status="active", error_message=None,
        )
        return TestConnectionResponse(success=True)

    except Exception as exc:
        error_msg = _sanitize_error(str(exc))
        logger.warning(
            "api.connections.test_failed",
            connection_id=connection_id,
            error=error_msg,
        )
        await store.update_connection_status(
            connection_id,
            status="error",
            error_message=error_msg,
        )
        return TestConnectionResponse(success=False, error=error_msg)


@router.post("/{connection_id}/sync/")
async def trigger_sync(
    connection_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace_id: str | None = Query(None),
) -> dict[str, str]:
    """Trigger a manual sync for a DB-based connection.

    Only works for connectors (not channels). Starts sync
    in the background and returns 202 Accepted.
    """
    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    conn = await store.get_connection_decrypted(connection_id, fernet_key)
    if conn is None or conn["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    connector_type = conn["connector_type"]
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    if not schema or schema.category != "connector":
        raise HTTPException(
            status_code=400,
            detail="Sync is only available for connectors, not channels",
        )

    if not conn.get("enabled", True):
        raise HTTPException(
            status_code=400, detail="Connection is disabled",
        )

    # Mark as syncing
    await store.update_connection_status(
        connection_id, status="syncing",
    )

    background_tasks.add_task(
        _run_connection_sync,
        connection_id=connection_id,
        connector_type=connector_type,
        config=conn["config"],
        workspace_id=ws_id,
        store=store,
    )

    return {
        "status": "sync_started",
        "connection_id": connection_id,
        "connector_type": connector_type,
    }


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


def _sanitize_error(error: str) -> str:
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


async def _run_connection_sync(
    connection_id: str,
    connector_type: str,
    config: dict[str, Any],
    workspace_id: str,
    store: PostgresStore,
) -> None:
    """Run sync for a DB-based connection. Async background task."""
    import asyncio
    import time
    import uuid
    from datetime import UTC, datetime

    from metatron.ingestion.pipeline import ingest_documents
    from metatron.storage.pg_connection import get_session
    from metatron.storage.pg_models import SyncLogRow

    sync_id = f"sync_{uuid.uuid4().hex[:12]}"
    start_time = time.perf_counter()
    status = "failed"
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
        registry = _get_registry()
        connector = registry.create(connector_type)

        connection_obj = Connection(
            id=connection_id,
            workspace_id=workspace_id,
            connector_type=connector_type,
        )

        await connector.configure(connection_obj, config)
        documents = await connector.fetch(workspace_id)
        documents_fetched = len(documents)

        logger.info(
            "sync.fetched",
            sync_id=sync_id,
            connector_type=connector_type,
            documents=documents_fetched,
        )

        if documents:
            # ingest_documents is sync — run in thread pool
            result = await asyncio.to_thread(
                ingest_documents, documents, workspace_id, connector_type,
            )
            documents_new = result.documents_new
            documents_updated = result.documents_updated
            documents_skipped = result.documents_skipped
            qdrant_chunks = (
                result.documents_new + result.documents_updated
            )

            if result.errors:
                errors_list = [
                    _sanitize_error(str(e))
                    for e in result.errors[:10]
                ]
                status = (
                    "partial" if result.documents_new > 0 else "failed"
                )
            else:
                status = "success"
        else:
            status = "success"

    except Exception as e:
        logger.error(
            "sync.db_connection.failed",
            sync_id=sync_id,
            connection_id=connection_id,
            error=str(e),
        )
        errors_list = [_sanitize_error(str(e))]
        status = "failed"

    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Update connection status
        final_status = (
            "active" if status == "success" else "error"
        )
        error_msg = (
            "; ".join(errors_list) if errors_list else None
        )
        try:
            await store.update_connection_status(
                connection_id,
                status=final_status,
                error_message=error_msg,
                last_synced_at=datetime.now(UTC),
            )
        except Exception as e:
            logger.warning(
                "sync.status_update_failed",
                connection_id=connection_id,
                error=str(e),
            )

        # Log sync result (sync ORM — run in thread pool)
        try:
            def _write_sync_log() -> None:
                with get_session() as session:
                    sync_log = SyncLogRow(
                        id=sync_id,
                        workspace_id=workspace_id,
                        connection_id=connection_id,
                        connector_type=connector_type,
                        status=status,
                        documents_fetched=documents_fetched,
                        documents_new=documents_new,
                        documents_updated=documents_updated,
                        documents_skipped=documents_skipped,
                        errors=errors_list,
                        duration_ms=duration_ms,
                        source_title=(
                            f"{connector_type.capitalize()} Sync"
                        ),
                        qdrant_chunks=qdrant_chunks,
                        created_at=datetime.now(UTC),
                    )
                    session.add(sync_log)

            await asyncio.to_thread(_write_sync_log)
            logger.info(
                "sync.logged",
                sync_id=sync_id,
                status=status,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning(
                "sync.log_failed", sync_id=sync_id, error=str(e),
            )
