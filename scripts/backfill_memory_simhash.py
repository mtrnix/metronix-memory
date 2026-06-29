#!/usr/bin/env python3
"""Backfill the ``content_simhash`` column on memory_records (PROJ-277).

Pre-ticket rows have ``content_simhash IS NULL``. This script computes
SimHash for each such row and writes it back with a single bulk-update
statement per batch. Idempotent — re-running is a safe no-op once all
rows have been populated.

Usage:
    python scripts/backfill_memory_simhash.py [--dry-run] \\
        [--batch-size 500] [--workspace-id MTRNIX]

When ``--workspace-id`` is omitted the script processes every workspace
in a single global pass (no per-workspace loop). Pass an explicit
``--workspace-id`` to restrict scope.

**Production recommendation (multi-tenant DBs).** The ``--workspace-id`` flag
exists to drive a per-tenant external loop on production-scale databases.
The default global pass holds one transaction per batch with no concurrency
between tenants and may starve other writers under load. For multi-million-row
deployments, prefer iterating workspace ids externally (shell loop or
Kubernetes Job array) and running the script with ``--workspace-id`` per
tenant — that way batches across tenants can interleave on the connection
pool and partial failures are scoped.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import get_settings
from metronix.ingestion.dedup import simhash
from metronix.storage.memory_postgres import MemoryPostgresStore


async def _process_workspace(
    pg: MemoryPostgresStore,
    workspace_id: str | None,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Scan and optionally update one workspace (or all if workspace_id is None).

    Returns ``(scanned, updated)``.
    """
    scanned = 0
    updated = 0

    async for batch in pg.iter_records_missing_simhash(
        workspace_id,
        batch_size=batch_size,
        dry_run=dry_run,
    ):
        scanned += len(batch)
        if dry_run:
            continue
        pairs = [(record_id, simhash(content)) for record_id, content in batch]
        n = await pg.bulk_set_simhash(pairs)
        updated += n

    return scanned, updated


async def _run(
    workspace_id: str | None,
    batch_size: int,
    dry_run: bool,
) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.postgres_dsn)
    pg = MemoryPostgresStore(engine)

    try:
        # Single pass — when workspace_id is None the iterator omits the
        # workspace filter entirely, draining every workspace in one query
        # series. No need to enumerate workspaces upfront.
        scanned, updated = await _process_workspace(pg, workspace_id, batch_size, dry_run)
        mode = "dry-run" if dry_run else "applied"
        print(f"backfill_memory_simhash ({mode}): scanned={scanned} updated={updated}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill content_simhash on memory_records (PROJ-277)."
    )
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Target workspace id. Omit to process all workspaces.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows to process per batch (default: 500).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan only; do not write simhash values.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.workspace_id, args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
