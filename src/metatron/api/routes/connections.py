"""Connections CRUD API + sync trigger — /api/v1/connections."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict

from metatron.connectors.registry import ConnectorRegistry, register_builtins
from metatron.core.config import Settings
from metatron.core.models import Connection

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


class SyncRequest(BaseModel):
    """Optional request body for sync trigger."""

    model_config = ConfigDict(strict=True)

    workspace_id: str | None = None


@router.get("/")
async def list_connections(workspace_id: str) -> list[ConnectionResponse]:
    """List all connections for a workspace."""
    logger.info("api.connections.list", workspace_id=workspace_id)
    # TODO: implement with PostgreSQL
    return []


@router.post("/", status_code=201)
async def create_connection(body: ConnectionCreate) -> ConnectionResponse:
    """Create a new data source connection.

    Encrypts the config before storing. Validates the connector
    type exists in the registry.
    """
    logger.info("api.connections.create", connector_type=body.connector_type)
    registry = _get_registry()
    if not registry.is_registered(body.connector_type):
        available = registry.list_available()
        raise HTTPException(
            status_code=400,
            detail=f"Unknown connector type '{body.connector_type}'. Available: {available}",
        )
    # TODO: encrypt body.config with Fernet and persist to PostgreSQL
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/{connection_id}/sync")
async def trigger_sync(
    connection_id: str,
    background_tasks: BackgroundTasks,
    body: SyncRequest | None = None,
) -> dict[str, str]:
    """Trigger a manual sync for a connection.

    Starts the sync in the background and returns immediately.
    """
    logger.info("api.connections.sync", connection_id=connection_id)
    # TODO: fetch connection from DB, decrypt config, run in background
    # For now, support env-based connector config for quick sync
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/sync/{connector_type}")
async def trigger_sync_by_type(
    connector_type: str,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Trigger a sync using env-based config (no DB connection required).

    Useful for dev/testing: reads connector credentials from environment.
    """
    registry = _get_registry()
    if not registry.is_registered(connector_type):
        available = registry.list_available()
        raise HTTPException(
            status_code=400,
            detail=f"Unknown connector type '{connector_type}'. Available: {available}",
        )

    settings = Settings()
    config = _config_from_env(connector_type, settings)
    if not config:
        raise HTTPException(
            status_code=400,
            detail=f"No environment config found for '{connector_type}'. Set the relevant env vars.",
        )

    workspace_id = settings.default_workspace_id
    background_tasks.add_task(_run_sync, connector_type, config, workspace_id)

    return {"status": "sync_started", "connector_type": connector_type, "workspace_id": workspace_id}


def _config_from_env(connector_type: str, settings: Settings) -> dict[str, str]:
    """Build connector config dict from environment variables."""
    if connector_type == "confluence":
        if not settings.confluence_url:
            return {}
        return {
            "url": settings.confluence_url,
            "username": settings.confluence_username,
            "api_token": settings.confluence_api_token,
            "space_key": settings.confluence_space_key,
        }
    if connector_type == "jira":
        if not settings.jira_url:
            return {}
        return {
            "url": settings.jira_url,
            "username": settings.jira_username,
            "api_token": settings.jira_api_token,
            "project_key": settings.jira_project_key,
        }
    if connector_type == "notion":
        if not settings.notion_api_token:
            return {}
        return {
            "api_token": settings.notion_api_token,
        }
    return {}


def _run_sync(connector_type: str, config: dict[str, str], workspace_id: str) -> None:
    """Run a connector sync: fetch → ingest. Runs as a background task.

    This is a regular (non-async) function so FastAPI runs it in a thread pool,
    preventing the blocking atlassian-python-api HTTP calls from freezing the event loop.
    """
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

    logger.info("sync.started", sync_id=sync_id, connector_type=connector_type, workspace_id=workspace_id)
    try:
        registry = _get_registry()
        connector = registry.create(connector_type)

        connection = Connection(
            workspace_id=workspace_id,
            connector_type=connector_type,
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(connector.configure(connection, config))
            documents = loop.run_until_complete(connector.fetch(workspace_id))
            documents_fetched = len(documents)
        finally:
            loop.close()

        logger.info("sync.fetched", sync_id=sync_id, connector_type=connector_type, documents=documents_fetched)

        if documents:
            result = ingest_documents(documents, workspace_id, connector_type)
            documents_new = result.documents_new
            documents_updated = result.documents_updated
            documents_skipped = result.documents_skipped
            qdrant_chunks = result.documents_new + result.documents_updated
            
            if result.errors:
                errors_list = [str(e) for e in result.errors[:10]]  # Limit to 10 errors
                status = "partial" if result.documents_new > 0 else "failed"
            else:
                status = "success"
            
            logger.info("sync.ingested",
                        sync_id=sync_id,
                        connector_type=connector_type,
                        new=result.documents_new,
                        skipped=result.documents_skipped,
                        errors=len(result.errors),
                        status=status)
        else:
            status = "success"  # No documents is not an error
            logger.info("sync.no_documents", sync_id=sync_id, connector_type=connector_type)

    except Exception as e:
        logger.error("sync.failed", sync_id=sync_id, connector_type=connector_type, error=str(e))
        errors_list = [str(e)]
        status = "failed"
    
    finally:
        # Log sync result to database
        duration_ms = (time.perf_counter() - start_time) * 1000
        try:
            with get_session() as session:
                sync_log = SyncLogRow(
                    id=sync_id,
                    workspace_id=workspace_id,
                    connection_id=None,  # NULL for env-based syncs
                    connector_type=connector_type,
                    status=status,
                    documents_fetched=documents_fetched,
                    documents_new=documents_new,
                    documents_updated=documents_updated,
                    documents_skipped=documents_skipped,
                    errors=errors_list,
                    duration_ms=duration_ms,
                    source_title=f"{connector_type.capitalize()} Sync",
                    qdrant_chunks=qdrant_chunks,
                    created_at=datetime.now(UTC),
                )
                session.add(sync_log)
                # Context manager auto-commits on exit
                logger.info("sync.logged", sync_id=sync_id, status=status, duration_ms=duration_ms)
        except Exception as e:
            logger.warning("sync.log_failed", sync_id=sync_id, error=str(e))


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: str) -> None:
    """Delete a connection and its encrypted credentials."""
    logger.info("api.connections.delete", connection_id=connection_id)
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not yet implemented")
