#!/usr/bin/env python3
"""Rebuild Memgraph knowledge graph from Qdrant stored documents.

Scrolls all unique documents from Qdrant, reconstructs minimal Document
objects from payload metadata, and replays graph extraction. Useful after
Memgraph data loss or cleanup.

Usage:
    python scripts/graph_rebuild.py --workspace MTRNIX
    python scripts/graph_rebuild.py --workspace MTRNIX --dry-run
    python scripts/graph_rebuild.py --workspace MTRNIX --source-type jira
"""

from __future__ import annotations

import argparse
import sys
import time

import structlog

sys.path.insert(0, "src")

from metatron.core.models import Document
from metatron.ingestion.pipeline import _extract_graphs_parallel
from metatron.storage.qdrant import get_hybrid_store

logger = structlog.get_logger(__name__)


def _scroll_unique_documents(
    workspace_id: str,
    source_type: str | None = None,
) -> list[dict]:
    """Scroll Qdrant and collect one representative chunk per unique doc_label."""
    store = get_hybrid_store(workspace_id)
    seen_labels: set[str] = set()
    documents: list[dict] = []
    offset = None

    payload_fields = [
        "doc_label",
        "title",
        "type",
        "source_id",
        "author",
        "date",
        "url",
        "workspace_id",
        "data",
        "memory",
        "source_role",
        "status",
        "assignee",
        "reporter",
        "issuetype",
        "priority",
        "created_at_str",
        "updated_at_str",
        "resolved_at_str",
    ]

    while True:
        results, offset = store.client.scroll(
            collection_name=store.collection_name,
            limit=100,
            offset=offset,
            with_payload=payload_fields,
            with_vectors=False,
        )
        for point in results:
            p = point.payload or {}
            label = p.get("doc_label", "")
            if not label or label in seen_labels:
                continue
            if source_type and p.get("type", "") != source_type:
                continue
            seen_labels.add(label)
            documents.append(p)

        if offset is None:
            break

    return documents


def _collect_full_content(workspace_id: str, doc_label: str) -> str:
    """Collect and concatenate all chunk texts for a document."""
    store = get_hybrid_store(workspace_id)
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    chunks_text: list[str] = []
    offset = None
    while True:
        results, offset = store.client.scroll(
            collection_name=store.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="doc_label", match=MatchValue(value=doc_label)),
                ]
            ),
            limit=100,
            offset=offset,
            with_payload=["data", "memory"],
            with_vectors=False,
        )
        for point in results:
            p = point.payload or {}
            text = p.get("data") or p.get("memory") or ""
            if text:
                chunks_text.append(text)
        if offset is None:
            break

    return "\n\n".join(chunks_text)


def _reconstruct_document(payload: dict) -> Document:
    """Reconstruct a minimal Document from Qdrant payload metadata."""
    content = payload.get("data") or payload.get("memory") or ""

    metadata: dict[str, str] = {}
    for key in (
        "status",
        "assignee",
        "reporter",
        "issuetype",
        "priority",
        "created_at_str",
        "updated_at_str",
        "resolved_at_str",
    ):
        val = payload.get(key)
        if val:
            metadata[key] = str(val)

    return Document(
        source_type=payload.get("type", ""),
        source_id=payload.get("source_id") or payload.get("doc_label", ""),
        title=payload.get("title", ""),
        content=content,
        url=payload.get("url", ""),
        author=payload.get("author", ""),
        source_role=payload.get("source_role", ""),
        metadata=metadata,
        workspace_id=payload.get("workspace_id", ""),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild Memgraph graph from Qdrant data")
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
    )

    docs_payload = _scroll_unique_documents(args.workspace, args.source_type)
    logger.info("graph_rebuild.documents_found", count=len(docs_payload))

    if not docs_payload:
        logger.info("graph_rebuild.nothing_to_rebuild")
        return

    if args.dry_run:
        for p in docs_payload:
            print(
                f"  {p.get('type', '?'):12s}  {p.get('doc_label', '?'):20s}"
                f"  {p.get('title', '')[:60]}"
            )
        print(f"\nTotal: {len(docs_payload)} documents would be rebuilt")
        return

    graph_queue: list[tuple[Document, str]] = []
    for i, payload in enumerate(docs_payload):
        doc = _reconstruct_document(payload)
        full_content = _collect_full_content(args.workspace, doc.source_id)
        if full_content:
            doc.content = full_content
        graph_queue.append((doc, args.workspace))
        if (i + 1) % 50 == 0:
            logger.info(
                "graph_rebuild.progress",
                reconstructed=i + 1,
                total=len(docs_payload),
            )

    logger.info("graph_rebuild.reconstructed", count=len(graph_queue))

    result = _extract_graphs_parallel(graph_queue, max_workers=args.workers)

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
