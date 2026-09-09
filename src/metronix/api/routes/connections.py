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
