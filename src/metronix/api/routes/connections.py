"""Connections CRUD API + sync trigger — /api/v1/connections."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog
from croniter import croniter  # type: ignore[import-untyped]
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from metronix.api.autosync import DEFAULT_SYNC_CRON, compute_next_run
from metronix.connectors.connection_sync import (
    ensure_workspace_exists,
    get_registry,
    run_connection_sync,
    sanitize_error,
)
from metronix.connectors.schemas import (
    CONNECTOR_SCHEMAS,
    validate_config,
    validate_config_for_update,
)
from metronix.core.models import Connection
from metronix.storage.postgres import PostgresStore

if TYPE_CHECKING:
    from metronix.core.config import Settings

logger = structlog.get_logger()

router = APIRouter(prefix="/connections", tags=["connections"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class CreateConnectionRequest(BaseModel):
    """Request body for creating a connection."""

    model_config = ConfigDict(strict=True)

    connector_type: str
    name: str
    config: dict[str, Any]
    sync_cron: str | None = None


class UpdateConnectionRequest(BaseModel):
    """Request body for updating a connection."""

    model_config = ConfigDict(strict=True)

    name: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    sync_cron: str | None = None


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
    sync_cron: str | None = None
    next_run_at: str | None = None


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
            connection_id,
            connector_type,
            config,
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
            error=sanitize_error(str(exc)),
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

    # Validate sync_cron only for connectors; channels never have a schedule.
    schema = CONNECTOR_SCHEMAS.get(body.connector_type)
    is_connector = schema is not None and schema.category == "connector"
    # Connectors default to the nightly schedule unless the caller overrides it.
    cron_to_set: str | None = (body.sync_cron or DEFAULT_SYNC_CRON) if is_connector else None
    if cron_to_set is not None:
        _validate_cron(cron_to_set)

    try:
        await ensure_workspace_exists(store, ws_id)
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
            detail=f"Failed to create connection: {sanitize_error(str(e))}",
        ) from None

    connection_id: str = result["id"]

    # Persist the schedule for connectors with next_run_at=NULL so the new
    # connector syncs immediately on the next scheduler tick (initial sync on
    # create). NULL = "due now", matching backfilled existing rows — no
    # asymmetry between fresh and existing connectors. Editing the schedule
    # later (update) computes the next occurrence instead ("tuning").
    if is_connector and cron_to_set is not None:
        await store.set_connection_schedule(connection_id, cron_to_set, None)
        result["sync_cron"] = cron_to_set
        result["next_run_at"] = None

    # Auto-start channel if ChannelManager is available
    if schema and schema.category == "channel":
        await _try_start_channel(
            request,
            connection_id,
            body.connector_type,
            body.config,
            ws_id,
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
            c
            for c in connections
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
    settings: Settings = request.app.state.settings

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
        # Masked secrets (``***``-prefixed) are treated as "unchanged" and
        # restored by ``merge_config`` in ``store.update_connection``.
        errors = validate_config_for_update(
            existing["connector_type"],
            body.config,
        )
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))
        updates["config"] = body.config

    # sync_cron update (only meaningful for connectors). Editing a schedule is
    # "tuning", so we compute the next occurrence (NOT NULL/"sync now").
    schedule_updated = False
    new_sync_cron: str | None = None
    new_next_run_at: datetime | None = None
    if body.sync_cron is not None:
        conn_schema = CONNECTOR_SCHEMAS.get(existing["connector_type"])
        if conn_schema and conn_schema.category == "connector":
            # Empty string clears the schedule; truthy string validates it.
            cron_value: str | None = body.sync_cron if body.sync_cron else None
            if cron_value is not None:
                _validate_cron(cron_value)
                new_next_run_at = compute_next_run(cron_value, timezone=settings.autosync_timezone)
            new_sync_cron = cron_value
            schedule_updated = True

    if not updates and not schedule_updated:
        raise HTTPException(
            status_code=422,
            detail="No fields to update",
        )

    if updates:
        try:
            result = await store.update_connection(
                connection_id,
                updates,
                fernet_key,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None

        if result is None:
            raise HTTPException(status_code=404, detail="Connection not found")
    else:
        # No config/name/enabled change, re-fetch to build the response.
        result = await store.get_connection(connection_id, fernet_key)
        if result is None:
            raise HTTPException(status_code=404, detail="Connection not found")

    if schedule_updated:
        await store.set_connection_schedule(connection_id, new_sync_cron, new_next_run_at)
        result["sync_cron"] = new_sync_cron
        result["next_run_at"] = new_next_run_at.isoformat() if new_next_run_at else None

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
            message=("Connection saved (test not available for this type)"),
        )

    registry = get_registry()
    if not registry.is_registered(connector_type):
        return TestConnectionResponse(
            success=True,
            message=("Connection saved (test not available for this type)"),
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
            connection_id,
            status="active",
            error_message=None,
        )
        return TestConnectionResponse(success=True)

    except Exception as exc:
        error_msg = sanitize_error(str(exc))
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
    force_full: bool = Query(
        False,
        description=(
            "Bypass the incremental sync watermark and refetch from the "
            "connector as if syncing for the first time. Use to force a "
            "one-off full resync (e.g. when the watermark has drifted "
            "past the most recent remote update). The successful sync "
            "still advances the watermark to NOW."
        ),
    ),
) -> dict[str, str]:
    """Trigger a manual sync for a DB-based connection.

    Writes a `sync_logs` row with status='running' SYNCHRONOUSLY before
    spawning the background task, so that a record exists even when the
    task is destroyed before reaching its finally block (API restart,
    CancelledError, hung LLM call). The background task then UPDATEs
    this row on completion or failure.

    ``force_full=true`` bypasses the incremental sync watermark so the
    connector performs a full fetch. The watermark is still advanced on
    success — this is a one-off reset, not a flag flip.
    """
    import uuid

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
        raise HTTPException(status_code=400, detail="Connection is disabled")

    # Best-effort guard against duplicate concurrent syncs. Two POSTs in quick
    # succession otherwise spawn two BackgroundTasks that fetch+embed+graph the
    # same payload in parallel — wasteful in general, expensive with
    # ``force_full=true``. This check is racy (no atomic CAS — between the read
    # above and the status update below another request can slip through) but
    # closes the common double-click / retry case. A race-free version requires
    # a conditional UPDATE on ``connections.status`` and is a separate ticket.
    if conn.get("status") == "syncing":
        raise HTTPException(
            status_code=409,
            detail="Sync already in progress for this connection",
        )

    # Mark connection as syncing
    await store.update_connection_status(connection_id, status="syncing")

    # Pre-insert a running sync_logs row so we always leave a trace, even
    # if the background task is destroyed before its finally block runs.
    sync_id = f"sync_{uuid.uuid4().hex[:12]}"
    try:
        await store.create_sync_log(
            sync_id=sync_id,
            workspace_id=ws_id,
            connection_id=connection_id,
            connector_type=connector_type,
            trigger="manual",
        )
    except Exception as e:
        # Non-fatal — sync still runs, but we lose visibility for this attempt.
        logger.warning("sync.create_log.failed", connection_id=connection_id, error=str(e))

    pm = getattr(request.app.state, "plugin_manager", None)
    event_bus = pm.get_event_bus() if pm is not None else None

    # PG cursor for incremental fetch (MTRNIX-332). ``get_connection_decrypted``
    # returns ``last_synced_at`` as an ISO string (or None for freshly-created
    # connections); the connector's ``fetch`` expects ``datetime | None`` so we
    # parse here at the boundary.
    last_synced_iso = conn.get("last_synced_at")
    last_synced_dt: datetime | None = None
    if last_synced_iso:
        try:
            last_synced_dt = datetime.fromisoformat(last_synced_iso)
        except (ValueError, TypeError):
            logger.warning(
                "sync.cursor_parse_failed",
                connection_id=connection_id,
                raw=last_synced_iso,
            )

    background_tasks.add_task(
        run_connection_sync,
        sync_id=sync_id,
        connection_id=connection_id,
        connector_type=connector_type,
        config=conn["config"],
        workspace_id=ws_id,
        store=store,
        event_bus=event_bus,
        force_full=force_full,
        last_synced_at=last_synced_dt,
    )

    return {
        "status": "sync_started",
        "sync_id": sync_id,
        "connection_id": connection_id,
        "connector_type": connector_type,
    }


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


def _validate_cron(sync_cron: str) -> None:
    """Validate a cron expression for the connections API.

    Raises:
        HTTPException(422): If ``sync_cron`` is not a valid cron expression.
    """
    if not croniter.is_valid(sync_cron):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression: {sync_cron!r}",
        )
