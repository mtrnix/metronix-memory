"""Connections CRUD API + sync trigger — /api/v1/connections."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

logger = structlog.get_logger()

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectionCreate(BaseModel):
    """Request body for creating a connection."""

    model_config = ConfigDict(strict=True)

    workspace_id: str
    connector_type: str
    config: dict[str, str]  # will be encrypted before storage


class ConnectionResponse(BaseModel):
    """Response body for a connection (config is NOT returned)."""

    model_config = ConfigDict(strict=True)

    id: str
    workspace_id: str
    connector_type: str
    status: str
    last_synced_at: str | None


@router.get("/")
async def list_connections(workspace_id: str) -> list[ConnectionResponse]:
    """List all connections for a workspace."""
    logger.info("api.connections.list", workspace_id=workspace_id)
    # TODO: implement
    return []


@router.post("/", status_code=201)
async def create_connection(body: ConnectionCreate) -> ConnectionResponse:
    """Create a new data source connection.

    Encrypts the config before storing. Validates the connector
    type exists in the registry.
    """
    logger.info("api.connections.create", connector_type=body.connector_type)
    # TODO: implement
    # 1. Validate connector_type in registry
    # 2. Encrypt body.config with Fernet
    # 3. Create Connection in postgres
    # 4. Return response
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/{connection_id}/sync")
async def trigger_sync(connection_id: str) -> dict[str, str]:
    """Trigger a manual sync for a connection.

    Starts the sync in the background and returns immediately.
    """
    logger.info("api.connections.sync", connection_id=connection_id)
    # TODO: implement
    # 1. Fetch connection from DB
    # 2. Decrypt config
    # 3. Create connector via registry
    # 4. Run fetch + ingest pipeline (background task)
    # 5. Return {"status": "sync_started", "connection_id": ...}
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: str) -> None:
    """Delete a connection and its encrypted credentials."""
    logger.info("api.connections.delete", connection_id=connection_id)
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not yet implemented")
