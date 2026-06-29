#!/usr/bin/env python3
"""Remove mirror duplicate-review entries (PROJ-395).

A possible-duplicate finding is undirected, but the freshness Reconciler used
to create a directed ``ReviewEntry`` per record. When both members of a pair
were processed, the queue ended up holding two rows for the same pair:
``(target=A, related=B)`` and the mirror ``(target=B, related=A)``. The
Reconciler now dedups undirectedly going forward and ``resolve_review``
cascade-deletes the mirror — this script cleans up the rows that accumulated
before the fix.

For each undirected pair flagged in both directions it keeps one entry
(deterministically the one whose ``target_id`` sorts first) and deletes the
mirror. Single-direction findings and non-paired reasons
(``low_confidence_decision``) are left untouched.

Idempotent — re-running after cleanup finds no remaining mirrors.

Usage:
    python scripts/cleanup_mirror_review_entries.py \\
        --workspace-id MTRNIX [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")

from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import get_settings
from metronix.storage.freshness_pg import FreshnessStore

_PAIRED_REASON = "possible_duplicate"


async def _run(workspace_id: str, dry_run: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.postgres_dsn)
    store = FreshnessStore(engine)

    deleted = 0
    pairs_collapsed = 0
    try:
        entries = await store.list_review_entries(
            workspace_id,
            target_kind="memory_record",
            reason=_PAIRED_REASON,
            limit=100000,
        )
        # Index directed entries by their (target, related) edge.
        by_edge: dict[tuple[str, str], str] = {}
        for e in entries:
            if not e.related_record_id:
                continue
            by_edge[(e.target_id, e.related_record_id)] = e.id

        handled: set[frozenset[str]] = set()
        for e in entries:
            if not e.related_record_id:
                continue
            pair = frozenset({e.target_id, e.related_record_id})
            if pair in handled or len(pair) < 2:
                continue
            forward = (e.target_id, e.related_record_id)
            mirror = (e.related_record_id, e.target_id)
            if mirror not in by_edge:
                continue  # only one direction — nothing to collapse
            handled.add(pair)
            pairs_collapsed += 1
            # Keep the entry whose target_id sorts first; delete the other.
            keep_edge, drop_edge = (
                (forward, mirror) if forward[0] <= mirror[0] else (mirror, forward)
            )
            drop_id = by_edge[drop_edge]
            print(
                f"pair {keep_edge[0]}<->{keep_edge[1]}: keep {by_edge[keep_edge]} drop {drop_id}"
            )
            if not dry_run:
                await store.delete_review_entry(workspace_id, drop_id)
                deleted += 1
    finally:
        await engine.dispose()

    mode = "dry-run" if dry_run else "applied"
    print(
        f"cleanup ({mode}): workspace={workspace_id} "
        f"mirror_pairs={pairs_collapsed} deleted={deleted}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove mirror duplicate-review entries (PROJ-395)."
    )
    parser.add_argument("--workspace-id", required=True, help="Target workspace id.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report mirror pairs without deleting.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.workspace_id, args.dry_run))


if __name__ == "__main__":
    main()
