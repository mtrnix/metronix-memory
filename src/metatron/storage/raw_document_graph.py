"""Neo4j helpers for :Document freshness graph edges (MTRNIX-313).

Mirrors the shape of :mod:`metatron.storage.memory_graph`: sync functions
called via ``asyncio.to_thread`` by the freshness pipeline. Best-effort —
callers wrap in try/except and never surface failures, since the graph is a
derived store and KB retrieval must keep working even when Neo4j is down.
"""

from __future__ import annotations

from typing import Any

import structlog

from metatron.storage.neo4j_graph import get_graph_driver, graph_retry

logger = structlog.get_logger()


@graph_retry()
def link_raw_documents_batch(
    workspace_id: str,
    edges: list[tuple[str, str, float]],
) -> None:
    """Create ``(:Document)-[:RELATED_TO {score}]->(:Document)`` edges.

    ``edges`` is a list of ``(src_doc_label, dst_doc_label, score)`` tuples.
    Matches on ``workspace_id`` so a stray edge cannot cross tenants even if
    the caller passes an unfiltered list.
    """
    if not edges:
        return
    driver = get_graph_driver()
    payload: list[dict[str, Any]] = [
        {"src": src, "dst": dst, "score": float(score)} for src, dst, score in edges
    ]
    with driver.session() as session:
        session.run(
            """
            UNWIND $edges AS e
            MATCH (a:Document {doc_label: e.src, workspace_id: $ws})
            MATCH (b:Document {doc_label: e.dst, workspace_id: $ws})
            MERGE (a)-[r:RELATED_TO]->(b)
            SET r.score = e.score
            """,
            {"ws": workspace_id, "edges": payload},
        )


@graph_retry()
def alias_raw_documents(
    workspace_id: str,
    source_doc_label: str,
    target_doc_label: str,
) -> None:
    """Merge an ``:ALIAS`` edge between two ``:Document`` nodes."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (a:Document {doc_label: $src, workspace_id: $ws})
            MATCH (b:Document {doc_label: $dst, workspace_id: $ws})
            MERGE (a)-[:ALIAS]->(b)
            """,
            {"src": source_doc_label, "dst": target_doc_label, "ws": workspace_id},
        )


@graph_retry()
def set_raw_document_status(
    workspace_id: str,
    doc_label: str,
    status: str,
) -> None:
    """Set the ``status`` property on a ``:Document`` node.

    Additive write — no index created. Useful for graph-side observability
    when retrieval traverses by :Document without hitting PG.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (d:Document {doc_label: $doc_label, workspace_id: $ws})
            SET d.status = $status
            """,
            {"doc_label": doc_label, "ws": workspace_id, "status": status},
        )
