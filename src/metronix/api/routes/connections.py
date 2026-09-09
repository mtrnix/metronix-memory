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
    release_unstarted_sync_claim,
    run_connection_sync,
    sanitize_error,
)
from metronix.connectors.schemas import (
    CONNECTOR_SCHEMAS,
    resolve_connector_type,
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


async def _try_stop_channel(request: Request, connection_id: str) -> None:
    """Stop a channel bot if ChannelManager is available on app.state.

    Non-fatal — logs warning on failure but never raises.
    """
    channel_manager = getattr(request.app.state, "channel_manager", None)
    if channel_manager is None:
        return
    try:
        await channel_manager.stop_channel(connection_id)
        logger.info("api.connections.channel_stopped", connection_id=connection_id)
    except Exception as exc:
        logger.warning(
            "api.connections.channel_stop.failed",
            connection_id=connection_id,
            error=sanitize_error(str(exc)),
        )


async def _try_restart_channel(
    request: Request,
    connection_id: str,
    connector_type: str,
    config: dict[str, Any],
    workspace_id: str,
) -> None:
    """Restart a channel bot (stop + start) if ChannelManager is available.

    Non-fatal — logs warning on failure but never raises. Used when a
    channel's config changes (e.g. bot_token rotation) or it is re-enabled,
    so the running poller always reflects the latest DB state — previously
    ``update_connection`` never touched ``channel_manager`` at all, so
    disabling/rotating a channel via this endpoint left the old poller
    running untouched.
    """
    channel_manager = getattr(request.app.state, "channel_manager", None)
    if channel_manager is None:
        return
    try:
        await channel_manager.restart_channel(
            connection_id,
            connector_type,
            config,
            workspace_id=workspace_id,
        )
        logger.info("api.connections.channel_restarted", connection_id=connection_id)
    except Exception as exc:
        logger.warning(
            "api.connections.channel_restart.failed",
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
    body.connector_type = resolve_connector_type(body.connector_type)
    logger.info("api.connections.create", connector_type=body.connector_type)

    if body.connector_type not in CONNECTOR_SCHEMAS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown connector type '{body.connector_type}'. "
                f"Available: {sorted(CONNECTOR_SCHEMAS.keys())}"
            ),
        )
