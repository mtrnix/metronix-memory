#!/usr/bin/env python3
"""Backfill the ``status`` payload field on memory Qdrant points (MTRNIX-314).

Pre-ticket points in ``mem_agent_memory_{workspace_id}`` have no ``status``
field in their payload. MTRNIX-314's exclude-filter semantics treat missing
``status`` as ``active`` (the safe default), so running this backfill is
optional. It is included so operators who want fully-tagged Qdrant points
can run it once per workspace.

Idempotent — re-running is safe and is effectively a no-op when all points
already carry the correct ``status`` (Qdrant's ``set_payload`` is an overwrite
for the keys given).

Usage:
    python scripts/backfill_memory_qdrant_status_payload.py \\
        --workspace-id MTRNIX [--batch-size 200] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")

from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.memory_qdrant import MemoryQdrantStore


async def _run(workspace_id: str, batch_size: int, dry_run: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.postgres_dsn)
    pg = MemoryPostgresStore(engine)
    qdrant = MemoryQdrantStore(workspace_id=workspace_id)

    total = 0
    written = 0
    offset = 0
    try:
        while True:
            rows = await pg.list_records(
                workspace_id,
                limit=batch_size,
                offset=offset,
            )
            if not rows:
                break
            total += len(rows)
            for rec in rows:
                if dry_run:
                    continue
                try:
                    await qdrant.update_payload(rec.id, {"status": rec.status.value})
                    written += 1
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[warn] failed to update payload for {rec.id}: {exc}",
                        file=sys.stderr,
                    )
            offset += batch_size
    finally:
        await qdrant.close()
        await engine.dispose()

    mode = "dry-run" if dry_run else "applied"
    print(f"backfill ({mode}): workspace={workspace_id} scanned={total} updated={written}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill status payload on memory Qdrant points (MTRNIX-314)."
    )
    parser.add_argument("--workspace-id", required=True, help="Target workspace id.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="PG page size and Qdrant update batch (default: 200).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan only; do not issue Qdrant updates.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.workspace_id, args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
