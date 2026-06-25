"""In-process graph sweeper.

Knowledge-base documents are persisted to ``raw_documents`` and indexed into
Qdrant synchronously, but graph extraction is LLM-bound and therefore deferred:
the ingesting call leaves ``graph_synced=false`` instead of blocking on it (see
``mcp.tools.store`` and the connector path). This sweeper is the durable,
bounded consumer of that backlog.

On each tick it asks PostgreSQL which workspaces still have ``graph_synced=false``
rows and runs ``process_all_unsynced_graphs`` for each, one at a time. Two safety
properties:

* **Single-flight per workspace** is NOT a property of this loop alone — the same
  ``process_all_unsynced_graphs`` is also called by connector syncs and uploads,
  and ``process_unsynced_graphs`` selects rows without claiming them. Concurrency
  is instead enforced inside ``process_all_unsynced_graphs`` via a per-workspace
  Postgres advisory lock, so the sweeper, a connector sync and an upload cannot
  re-extract the same documents at once.
* **Self-healing**: re-scanning every tick means a row left behind by a crash or a
  transient Neo4j/LLM failure is simply retried on the next tick.

Each tick processes at most one batch per workspace (``max_rounds=1``) so a large
backlog drains gradually across ticks rather than in one unbounded burst (e.g.
right after an upgrade enables the sweeper).

Layer: L6 — API. Imports from L2 (ingestion.pipeline) and L1 (storage) only.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from metronix.core.config import Settings
    from metronix.storage.postgres import PostgresStore

logger = structlog.get_logger(__name__)


class GraphSweeper:
    """Poll for workspaces with unsynced graphs and process them in batches.

    Constructed once in ``lifespan()`` and run as a long-lived ``asyncio.Task``.
    The heavy work is delegated to ``process_all_unsynced_graphs`` (L2); this
    class is only the scheduling shell.
    """

    def __init__(self, store: PostgresStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    async def run_forever(self) -> None:
        """Main sweep loop. Run as an asyncio.Task by lifespan().

        Sleeps ``graph_sweep_poll_seconds`` between ticks. A failing tick is
        logged and skipped — one bad tick must never kill the loop.
        ``asyncio.CancelledError`` is re-raised immediately (clean shutdown).
        """
        logger.info(
            "graph_sweep.loop.started",
            poll_seconds=self._settings.graph_sweep_poll_seconds,
        )
        while True:
            try:
                await asyncio.sleep(self._settings.graph_sweep_poll_seconds)
                await self.tick()
            except asyncio.CancelledError:
                logger.info("graph_sweep.loop.cancelled")
                raise
            except Exception:
                logger.warning("graph_sweep.tick.error", exc_info=True)

    async def tick(self) -> None:
        """Single sweep: process the graph backlog of every affected workspace."""
        workspaces = await self._store.list_workspaces_with_unsynced_graphs()
        if not workspaces:
            return

        # Imported lazily to avoid importing the heavy ingestion pipeline at
        # module load (and to keep the L6->L2 edge explicit).
        from metronix.ingestion.pipeline import process_all_unsynced_graphs

        logger.info("graph_sweep.tick.workspaces", count=len(workspaces))
        for workspace_id in workspaces:
            try:
                # max_rounds=1: at most one batch (~1000 docs) per workspace per
                # tick, so a big backlog drains gradually instead of all at once.
                result = await process_all_unsynced_graphs(
                    workspace_id, self._store, max_rounds=1
                )
                logger.info(
                    "graph_sweep.workspace.done",
                    workspace_id=workspace_id,
                    ok=result.get("ok"),
                    errors=result.get("errors"),
                    rounds=result.get("rounds"),
                )
            except Exception:
                # One workspace failing (e.g. Neo4j hiccup) must not block the
                # rest; the row stays graph_synced=false and is retried next tick.
                logger.warning(
                    "graph_sweep.workspace.error",
                    workspace_id=workspace_id,
                    exc_info=True,
                )
