#!/usr/bin/env python3
"""Rebuild Neo4j knowledge graph from PostgreSQL raw_documents.

Reads documents from raw_documents table (source of truth), reconstructs
minimal Document objects, and replays graph extraction. Useful after
Neo4j data loss or cleanup.

Usage:
    python scripts/graph_rebuild.py --workspace MTRNIX
    python scripts/graph_rebuild.py --workspace MTRNIX --dry-run
    python scripts/graph_rebuild.py --workspace MTRNIX --source-type jira
    python scripts/graph_rebuild.py --workspace MTRNIX --force
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import structlog
from sqlalchemy import text as sa_text

sys.path.insert(0, "src")

from metronix.core.models import Document
from metronix.ingestion.pipeline import _extract_graphs_parallel
from metronix.storage.pg_connection import get_session

logger = structlog.get_logger(__name__)


def _query_documents(
    workspace_id: str,
    source_type: str | None = None,
    force: bool = False,
) -> list[dict]:
    """Query raw_documents from PostgreSQL for graph rebuild."""
    with get_session() as session:
        query = """
            SELECT * FROM raw_documents
            WHERE workspace_id = :ws AND (NOT graph_synced OR :force)
            ORDER BY fetched_at
        """
        params: dict = {"ws": workspace_id, "force": force}

        if source_type:
            query = """
                SELECT * FROM raw_documents
                WHERE workspace_id = :ws
                  AND connector_type = :source_type
                  AND (NOT graph_synced OR :force)
                ORDER BY fetched_at
            """
            params["source_type"] = source_type

        result = session.execute(sa_text(query), params)
        return [dict(row._mapping) for row in result]


def _reconstruct_document(row: dict) -> Document:
    """Reconstruct a Document from a PostgreSQL raw_documents row."""
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    return Document(
        source_type=row.get("connector_type", ""),
        source_id=row.get("source_id", ""),
        title=row.get("title") or "",
        content=row.get("content") or "",
        url=row.get("url") or "",
        author=row.get("author") or "",
        source_role=row.get("source_role") or "",
        metadata=metadata,
        created_at=row.get("source_created_at") or row.get("created_at"),
        updated_at=row.get("source_updated_at") or row.get("updated_at"),
    )


def _mark_graph_synced(workspace_id: str, source_ids: list[str]) -> None:
    """Mark documents as graph_synced in PostgreSQL."""
    if not source_ids:
        return
    with get_session() as session:
        session.execute(
            sa_text("""
                UPDATE raw_documents
                SET graph_synced = true, graph_synced_at = NOW()
                WHERE workspace_id = :ws AND source_id = ANY(:ids)
            """),
            {"ws": workspace_id, "ids": source_ids},
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild Neo4j graph from PostgreSQL raw_documents"
    )
    parser.add_argument("--workspace", default="MTRNIX", help="Workspace ID (default: MTRNIX)")
    parser.add_argument(
        "--source-type",
        default=None,
        help="Filter by source type (jira, confluence, etc.)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be rebuilt without writing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild ALL docs (ignore graph_synced flag)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Max parallel graph extraction workers (default: 2)",
    )
    args = parser.parse_args()

    t0 = time.time()
    logger.info(
        "graph_rebuild.start",
        workspace=args.workspace,
        source_type=args.source_type,
        force=args.force,
    )

    rows = _query_documents(args.workspace, args.source_type, args.force)
    logger.info("graph_rebuild.documents_found", count=len(rows))

    if not rows:
        logger.info("graph_rebuild.nothing_to_rebuild")
        return

    if args.dry_run:
        for row in rows:
            print(
                f"  {row.get('connector_type', '?'):12s}"
                f"  {row.get('source_id', '?'):20s}"
                f"  {(row.get('title') or '')[:60]}"
            )
        print(f"\nTotal: {len(rows)} documents would be rebuilt")
        return

    graph_queue: list[tuple[Document, str]] = []
    for i, row in enumerate(rows):
        doc = _reconstruct_document(row)
        if doc.content and doc.content.strip():
            graph_queue.append((doc, args.workspace))
        if (i + 1) % 50 == 0:
            logger.info(
                "graph_rebuild.progress",
                reconstructed=i + 1,
                total=len(rows),
            )

    logger.info("graph_rebuild.reconstructed", count=len(graph_queue))

    result = _extract_graphs_parallel(graph_queue, max_workers=args.workers)

    # Mark successfully processed documents as graph_synced
    failed_ids = set(result.get("failed_source_ids", []))
    ok_ids = [doc.source_id for doc, _ in graph_queue if doc.source_id not in failed_ids]
    if ok_ids:
        _mark_graph_synced(args.workspace, ok_ids)
        logger.info("graph_rebuild.marked_synced", count=len(ok_ids))

    elapsed = time.time() - t0
    logger.info(
        "graph_rebuild.complete",
        ok=result["ok"],
        errors=result["errors"],
        skipped=result["skipped"],
        total_docs=len(graph_queue),
        elapsed=f"{elapsed:.1f}s",
    )
    print(
        f"\nGraph rebuild complete: {result['ok']} ok, "
        f"{result['errors']} errors, "
        f"{result['skipped']} skipped ({elapsed:.1f}s)"
    )


if __name__ == "__main__":
    main()
