"""Startup recovery for interrupted syncs.

If the API is killed mid-sync (restart, SIGKILL, CancelledError), the
background `_run_connection_sync` task never reaches its finally block.
This leaves:
  - `sync_logs` rows with status='running' forever
  - `connections` rows with status='syncing' forever (blocking the UI Sync button)

`recover_interrupted_syncs()` is called once in the API lifespan (after
migrations, before serving) and flips both back to a terminal error state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import text

from metronix.storage.pg_connection import get_session

logger = structlog.get_logger()


_INTERRUPTED_MSG = "Sync interrupted (API restart). Please retry."


def recover_interrupted_syncs() -> dict[str, int]:
    """Reset any stuck `running` sync_logs and `syncing` connections.

    Returns:
        {"sync_logs_reset": N, "connections_reset": M}
    """
    result = {"sync_logs_reset": 0, "connections_reset": 0}

    try:
        with get_session() as session:
            now = datetime.now(UTC)

            # 1) sync_logs.status='running' → 'failed'
            sync_logs_rows = session.execute(
                text(
                    "UPDATE sync_logs SET "
                    "  status = 'failed', "
                    "  errors = CAST(:err AS jsonb), "
                    "  duration_ms = COALESCE(EXTRACT(EPOCH FROM (:now - created_at)) * 1000, 0) "
                    "WHERE status = 'running' "
                    "RETURNING id"
                ),
                {
                    "err": json.dumps([_INTERRUPTED_MSG]),
                    "now": now,
                },
            )
            result["sync_logs_reset"] = len(sync_logs_rows.fetchall())

            # 2) connections.status='syncing' → 'error'
            conn_rows = session.execute(
                text(
                    "UPDATE connections SET "
                    "  status = 'error', "
                    "  error_message = :msg "
                    "WHERE status = 'syncing' "
                    "RETURNING id"
                ),
                {"msg": _INTERRUPTED_MSG},
            )
            result["connections_reset"] = len(conn_rows.fetchall())

        logger.info(
            "sync.recovery.done",
            sync_logs_reset=result["sync_logs_reset"],
            connections_reset=result["connections_reset"],
        )
    except Exception as exc:
        logger.warning("sync.recovery.failed", error=str(exc))

    return result
