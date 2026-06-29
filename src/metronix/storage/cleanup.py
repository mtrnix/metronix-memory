"""Database cleanup utilities.

Migrated from PoC metronix/db/cleanup.py.
Provides functions to clear data from Qdrant and Neo4j.

Safety: requires ALLOW_CLEANUP=true env var in production.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from qdrant_client import QdrantClient

from metronix.storage.neo4j_graph import graph_retry

logger = structlog.get_logger()

ALLOW_CLEANUP = os.getenv("ALLOW_CLEANUP", "false").lower() == "true"


class CleanupError(Exception):
    """Error during cleanup operation."""


def _check_cleanup_allowed() -> None:
    if not ALLOW_CLEANUP:
        raise CleanupError(
            "Cleanup is disabled. Set ALLOW_CLEANUP=true to enable. "
            "WARNING: This will permanently delete data!"
        )


def _get_qdrant_client() -> QdrantClient:
    from metronix.core.config import Settings

    settings = Settings()
    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
        timeout=60,
        api_key=settings.qdrant_api_key or None,
        https=settings.qdrant_https,
    )


def list_qdrant_collections() -> list[str]:
    client = _get_qdrant_client()
    collections = client.get_collections().collections
    return [c.name for c in collections]


def cleanup_qdrant_workspace(workspace_id: str) -> dict[str, Any]:
    """Delete Qdrant collection for a specific workspace."""
    collection_name = f"mem_docs_hybrid_{workspace_id}"
    client = _get_qdrant_client()

    try:
        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            return {"status": "skipped", "collection": collection_name, "reason": "not found"}

        info = client.get_collection(collection_name)
        points_count = info.points_count
        client.delete_collection(collection_name)
        logger.info("cleanup.qdrant.deleted", collection=collection_name, points=points_count)
        return {"status": "deleted", "collection": collection_name, "points_deleted": points_count}
    except Exception as e:
        logger.error("cleanup.qdrant.error", collection=collection_name, error=str(e))
        return {"status": "error", "collection": collection_name, "error": str(e)}


def cleanup_qdrant_all() -> dict[str, Any]:
    """Delete ALL metronix Qdrant collections."""
    client = _get_qdrant_client()
    collections = list_qdrant_collections()
    metronix_collections = [c for c in collections if c.startswith("mem_docs_hybrid")]

    results = []
    total_points = 0

    for name in metronix_collections:
        try:
            info = client.get_collection(name)
            pts = info.points_count
            total_points += pts
            client.delete_collection(name)
            results.append({"collection": name, "status": "deleted", "points_deleted": pts})
        except Exception as e:
            results.append({"collection": name, "status": "error", "error": str(e)})

    return {
        "status": "completed",
        "collections_deleted": len([r for r in results if r["status"] == "deleted"]),
        "total_points_deleted": total_points,
        "details": results,
    }


@graph_retry()
def cleanup_graph_workspace(workspace_id: str) -> dict[str, Any]:
    """Delete all Neo4j nodes for a workspace."""
    from metronix.storage.neo4j_graph import get_graph_driver

    driver = get_graph_driver()
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (n) WHERE n.workspace_id = $ws RETURN count(n)",
                {"ws": workspace_id},
            )
            count = result.single()[0]
            if count == 0:
                return {"status": "skipped", "workspace_id": workspace_id, "reason": "no nodes"}
            session.run(
                "MATCH (n) WHERE n.workspace_id = $ws DETACH DELETE n",
                {"ws": workspace_id},
            )
            logger.info("cleanup.graph.deleted", workspace_id=workspace_id, nodes=count)
            return {"status": "deleted", "workspace_id": workspace_id, "nodes_deleted": count}
    except (ServiceUnavailable, SessionExpired, BrokenPipeError, ConnectionError):
        raise  # let graph_retry handle these
    except Exception as e:
        logger.error("cleanup.graph.error", workspace_id=workspace_id, error=str(e))
        return {"status": "error", "workspace_id": workspace_id, "error": str(e)}


@graph_retry()
def cleanup_graph_all() -> dict[str, Any]:
    """Delete ALL nodes and relationships from Neo4j."""
    from metronix.storage.neo4j_graph import get_graph_driver

    driver = get_graph_driver()
    try:
        with driver.session() as session:
            r1 = session.run("MATCH (n) RETURN count(n)")
            node_count = r1.single()[0]
            r2 = session.run("MATCH ()-[r]->() RETURN count(r)")
            rel_count = r2.single()[0]

            if node_count == 0:
                return {"status": "skipped", "reason": "empty"}

            session.run("MATCH (n) DETACH DELETE n")
            logger.info("cleanup.graph.all.deleted", nodes=node_count, rels=rel_count)
            return {
                "status": "deleted",
                "nodes_deleted": node_count,
                "relationships_deleted": rel_count,
            }
    except (ServiceUnavailable, SessionExpired, BrokenPipeError, ConnectionError):
        raise  # let graph_retry handle these
    except Exception as e:
        return {"status": "error", "error": str(e)}


def cleanup_workspace(workspace_id: str, confirm: bool = False) -> dict[str, Any]:
    """Clean up all data for a workspace (Qdrant + Neo4j)."""
    _check_cleanup_allowed()
    if not confirm:
        raise CleanupError("Cleanup requires confirm=True")
    logger.warning("cleanup.workspace.start", workspace_id=workspace_id)
    graph_result = cleanup_graph_workspace(workspace_id)
    results: dict[str, Any] = {
        "workspace_id": workspace_id,
        "qdrant": cleanup_qdrant_workspace(workspace_id),
        "memgraph": graph_result,  # deprecated, use neo4j
        "neo4j": graph_result,
    }
    statuses = [results["qdrant"]["status"], results["neo4j"]["status"]]
    if "error" in statuses:
        results["status"] = "partial"
    elif all(s == "skipped" for s in statuses):
        results["status"] = "skipped"
    else:
        results["status"] = "completed"
    return results


def cleanup_all(confirm: bool = False) -> dict[str, Any]:
    """Clean up ALL data from ALL databases."""
    _check_cleanup_allowed()
    if not confirm:
        raise CleanupError("Full cleanup requires confirm=True")
    logger.warning("cleanup.all.start")
    graph_result = cleanup_graph_all()
    results: dict[str, Any] = {
        "qdrant": cleanup_qdrant_all(),
        "memgraph": graph_result,  # deprecated, use neo4j
        "neo4j": graph_result,
    }
    if results["qdrant"]["status"] == "error" or results["neo4j"]["status"] == "error":
        results["status"] = "partial"
    else:
        results["status"] = "completed"
    return results


def get_cleanup_preview() -> dict[str, Any]:
    """Dry run — preview what would be deleted."""
    preview: dict[str, Any] = {
        "qdrant": {"collections": [], "total_points": 0},
        "memgraph": {"nodes": 0, "relationships": 0, "workspaces": []},  # deprecated
        "neo4j": {"nodes": 0, "relationships": 0, "workspaces": []},
    }
    try:
        client = _get_qdrant_client()
        for name in list_qdrant_collections():
            if name.startswith("mem_docs_hybrid"):
                info = client.get_collection(name)
                preview["qdrant"]["collections"].append(
                    {"name": name, "points": info.points_count}
                )
                preview["qdrant"]["total_points"] += info.points_count
    except Exception as e:
        preview["qdrant"]["error"] = str(e)

    try:
        from metronix.storage.neo4j_graph import get_graph_driver

        driver = get_graph_driver()
        with driver.session() as session:
            r = session.run("MATCH (n) RETURN count(n)")
            node_count = r.single()[0]
            r = session.run("MATCH ()-[r]->() RETURN count(r)")
            rel_count = r.single()[0]
            for key in ("memgraph", "neo4j"):
                preview[key]["nodes"] = node_count
                preview[key]["relationships"] = rel_count
    except Exception as e:
        for key in ("memgraph", "neo4j"):
            preview[key]["error"] = str(e)

    preview["cleanup_allowed"] = ALLOW_CLEANUP
    return preview
