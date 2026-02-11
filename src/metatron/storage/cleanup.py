"""Database cleanup utilities.

Migrated from PoC metatron/db/cleanup.py.
Provides functions to clear data from Qdrant and Memgraph.

Safety: requires ALLOW_CLEANUP=true env var in production.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from qdrant_client import QdrantClient

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
    from metatron.core.config import Settings
    settings = Settings()
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_http_port, timeout=60)


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
    """Delete ALL metatron Qdrant collections."""
    client = _get_qdrant_client()
    collections = list_qdrant_collections()
    metatron_collections = [c for c in collections if c.startswith("mem_docs_hybrid")]

    results = []
    total_points = 0

    for name in metatron_collections:
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


def cleanup_memgraph_workspace(workspace_id: str) -> dict[str, Any]:
    """Delete all Memgraph nodes for a workspace."""
    from metatron.storage.memgraph import get_memgraph_driver

    driver = get_memgraph_driver()
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (n) WHERE n.workspace_id = $wid RETURN count(n) AS cnt",
                {"wid": workspace_id},
            )
            count = result.single()["cnt"]
            if count == 0:
                return {"status": "skipped", "workspace_id": workspace_id, "reason": "no nodes"}
            session.run(
                "MATCH (n) WHERE n.workspace_id = $wid DETACH DELETE n",
                {"wid": workspace_id},
            )
            logger.info("cleanup.memgraph.deleted", workspace_id=workspace_id, nodes=count)
            return {"status": "deleted", "workspace_id": workspace_id, "nodes_deleted": count}
    except Exception as e:
        logger.error("cleanup.memgraph.error", workspace_id=workspace_id, error=str(e))
        return {"status": "error", "workspace_id": workspace_id, "error": str(e)}


def cleanup_memgraph_all() -> dict[str, Any]:
    """Delete ALL nodes and relationships from Memgraph."""
    from metatron.storage.memgraph import get_memgraph_driver

    driver = get_memgraph_driver()
    try:
        with driver.session() as session:
            r1 = session.run("MATCH (n) RETURN count(n) AS cnt")
            node_count = r1.single()["cnt"]
            r2 = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            rel_count = r2.single()["cnt"]

            if node_count == 0:
                return {"status": "skipped", "reason": "empty"}

            session.run("MATCH (n) DETACH DELETE n")
            logger.info("cleanup.memgraph.all.deleted", nodes=node_count, rels=rel_count)
            return {"status": "deleted", "nodes_deleted": node_count, "relationships_deleted": rel_count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def cleanup_workspace(workspace_id: str, confirm: bool = False) -> dict[str, Any]:
    """Clean up all data for a workspace (Qdrant + Memgraph)."""
    _check_cleanup_allowed()
    if not confirm:
        raise CleanupError("Cleanup requires confirm=True")
    logger.warning("cleanup.workspace.start", workspace_id=workspace_id)
    results: dict[str, Any] = {
        "workspace_id": workspace_id,
        "qdrant": cleanup_qdrant_workspace(workspace_id),
        "memgraph": cleanup_memgraph_workspace(workspace_id),
    }
    statuses = [results["qdrant"]["status"], results["memgraph"]["status"]]
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
    results: dict[str, Any] = {
        "qdrant": cleanup_qdrant_all(),
        "memgraph": cleanup_memgraph_all(),
    }
    if results["qdrant"]["status"] == "error" or results["memgraph"]["status"] == "error":
        results["status"] = "partial"
    else:
        results["status"] = "completed"
    return results


def get_cleanup_preview() -> dict[str, Any]:
    """Dry run — preview what would be deleted."""
    preview: dict[str, Any] = {
        "qdrant": {"collections": [], "total_points": 0},
        "memgraph": {"nodes": 0, "relationships": 0, "workspaces": []},
    }
    try:
        client = _get_qdrant_client()
        for name in list_qdrant_collections():
            if name.startswith("mem_docs_hybrid"):
                info = client.get_collection(name)
                preview["qdrant"]["collections"].append({"name": name, "points": info.points_count})
                preview["qdrant"]["total_points"] += info.points_count
    except Exception as e:
        preview["qdrant"]["error"] = str(e)

    try:
        from metatron.storage.memgraph import get_memgraph_driver
        driver = get_memgraph_driver()
        with driver.session() as session:
            r = session.run("MATCH (n) RETURN count(n) AS cnt")
            preview["memgraph"]["nodes"] = r.single()["cnt"]
            r = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            preview["memgraph"]["relationships"] = r.single()["cnt"]
    except Exception as e:
        preview["memgraph"]["error"] = str(e)

    preview["cleanup_allowed"] = ALLOW_CLEANUP
    return preview
