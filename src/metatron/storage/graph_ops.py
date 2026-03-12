"""Memgraph graph query/read operations (workspace-aware).

Migrated from PoC: metatron_experiments/metatron/indexers/memgraph_workspace.py
"""
# TODO: async migration
from __future__ import annotations
from typing import Dict, List, Optional

import structlog

from metatron.storage.memgraph import get_memgraph_driver, memgraph_retry, DEFAULT_WORKSPACE_ID

logger = structlog.get_logger()


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


@memgraph_retry()
def get_graph_entities(texts: List[str], workspace_id: Optional[str] = None) -> List[Dict]:
    """Get entities mentioned in documents matching given texts."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d.raw_text IN $texts "
                "AND (d.workspace_id = $ws OR d.workspace_id IS NULL) "
                "OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity) "
                "WITH e, alias "
                "RETURN DISTINCT e.name AS name, e.type AS type, "
                "COLLECT(DISTINCT alias.name) AS aliases",
                {"texts": texts, "ws": workspace_id},
            )
        else:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d.raw_text IN $texts AND d.workspace_id = $ws AND e.workspace_id = $ws "
                "OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity) "
                "WHERE alias.workspace_id = $ws "
                "WITH e, alias "
                "RETURN DISTINCT e.name AS name, e.type AS type, "
                "COLLECT(DISTINCT alias.name) AS aliases",
                {"texts": texts, "ws": workspace_id},
            )
        return [{"name": r["name"], "type": r["type"],
                 "aliases": [a for a in r["aliases"] if a]} for r in ent_res]


@memgraph_retry()
def get_entities_by_doc_labels(doc_labels: List[str],
                               workspace_id: Optional[str] = None) -> List[Dict]:
    """Get entities mentioned in documents by doc_label."""
    labels = [l for l in doc_labels if l]
    if not labels:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d) WHERE (d:Document OR d:JiraIssue) "
                "AND d.doc_label IN $labels "
                "AND (d.workspace_id = $ws OR d.workspace_id IS NULL) "
                "MATCH (d)-[:MENTIONS]->(e:Entity) "
                "OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity) "
                "WITH e, alias "
                "RETURN DISTINCT e.name AS name, e.type AS type, "
                "COLLECT(DISTINCT alias.name) AS aliases",
                {"labels": labels, "ws": workspace_id},
            )
        else:
            ent_res = s.run(
                "MATCH (d) WHERE (d:Document OR d:JiraIssue) "
                "AND d.doc_label IN $labels AND d.workspace_id = $ws "
                "MATCH (d)-[:MENTIONS]->(e:Entity) WHERE e.workspace_id = $ws "
                "OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity) WHERE alias.workspace_id = $ws "
                "WITH e, alias "
                "RETURN DISTINCT e.name AS name, e.type AS type, "
                "COLLECT(DISTINCT alias.name) AS aliases",
                {"labels": labels, "ws": workspace_id},
            )
        return [{"name": r["name"], "type": r["type"],
                 "aliases": [a for a in r["aliases"] if a]} for r in ent_res]


@memgraph_retry()
def get_all_workspace_entities(workspace_id: Optional[str] = None,
                               limit: int = 100) -> List[Dict]:
    """Get all entities in a workspace."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            res = s.run(
                "MATCH (e:Entity) "
                "WHERE e.workspace_id = $ws OR e.workspace_id IS NULL "
                "RETURN DISTINCT e.name AS name, e.type AS type LIMIT $lim",
                {"ws": workspace_id, "lim": limit},
            )
        else:
            res = s.run(
                "MATCH (e:Entity) WHERE e.workspace_id = $ws "
                "RETURN DISTINCT e.name AS name, e.type AS type LIMIT $lim",
                {"ws": workspace_id, "lim": limit},
            )
        return [{"name": r["name"], "type": r["type"]} for r in res]


@memgraph_retry()
def get_graph_relationships(entity_names: List[str],
                            workspace_id: Optional[str] = None,
                            max_depth: int = 5,
                            active_only: bool = False) -> List[Dict]:
    """Get relationships for entities (variable depth traversal).

    Args:
        active_only: When True, only return relationships where valid_to IS NULL
                     (i.e. currently active / not closed).
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(max_depth, 5))
    active_filter = "AND r.valid_to IS NULL " if active_only else ""
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            rel_res = s.run(
                f"MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity) "
                "WHERE e.name IN $names "
                "UNWIND range(0, size(rels)-1) AS idx "
                "WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2 "
                f"WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL {active_filter}"
                "RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type, "
                "r.valid_from AS valid_from, r.valid_to AS valid_to "
                "LIMIT 200",
                {"names": entity_names},
            )
        else:
            rel_res = s.run(
                f"MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity) "
                "WHERE e.name IN $names AND e.workspace_id = $ws AND e2.workspace_id = $ws "
                "UNWIND range(0, size(rels)-1) AS idx "
                "WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2 "
                f"WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL {active_filter}"
                "RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type, "
                "r.valid_from AS valid_from, r.valid_to AS valid_to "
                "LIMIT 200",
                {"names": entity_names, "ws": workspace_id},
            )
        return [{"source": r["source"], "target": r["target"],
                 "type": r["rel_type"],
                 "valid_from": r["valid_from"], "valid_to": r["valid_to"]}
                for r in rel_res]


@memgraph_retry()
def get_relationships_at_date(entity_names: List[str],
                              target_date: str,
                              workspace_id: Optional[str] = None,
                              max_depth: int = 5) -> List[Dict]:
    """Get relationships valid at a specific date (ISO format YYYY-MM-DD).

    Returns relationships where:
    - valid_from is NULL or <= target_date
    - valid_to is NULL or >= target_date
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(max_depth, 5))
    date_filter = (
        "AND (r.valid_from IS NULL OR r.valid_from <= $target_date) "
        "AND (r.valid_to IS NULL OR r.valid_to >= $target_date) "
    )
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            rel_res = s.run(
                f"MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity) "
                "WHERE e.name IN $names "
                "UNWIND range(0, size(rels)-1) AS idx "
                "WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2 "
                f"WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL {date_filter}"
                "RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type, "
                "r.valid_from AS valid_from, r.valid_to AS valid_to "
                "LIMIT 200",
                {"names": entity_names, "target_date": target_date},
            )
        else:
            rel_res = s.run(
                f"MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity) "
                "WHERE e.name IN $names AND e.workspace_id = $ws AND e2.workspace_id = $ws "
                "UNWIND range(0, size(rels)-1) AS idx "
                "WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2 "
                f"WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL {date_filter}"
                "RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type, "
                "r.valid_from AS valid_from, r.valid_to AS valid_to "
                "LIMIT 200",
                {"names": entity_names, "ws": workspace_id,
                 "target_date": target_date},
            )
        return [{"source": r["source"], "target": r["target"],
                 "type": r["rel_type"],
                 "valid_from": r["valid_from"], "valid_to": r["valid_to"]}
                for r in rel_res]


@memgraph_retry()
def get_doc_labels_by_entities(entity_names: List[str],
                               workspace_id: Optional[str] = None) -> List[Dict]:
    """Get document labels for documents linked to given entities."""
    if not entity_names:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        ws_filter = "(e.workspace_id = $ws OR e.workspace_id IS NULL)" if workspace_id == DEFAULT_WORKSPACE_ID else "e.workspace_id = $ws"
        d_filter = "(d.workspace_id = $ws OR d.workspace_id IS NULL)" if workspace_id == DEFAULT_WORKSPACE_ID else "d.workspace_id = $ws"
        doc_res = s.run(
            f"MATCH (e:Entity) WHERE e.name IN $names AND {ws_filter} "
            "WITH DISTINCT e UNWIND COALESCE(e.doc_labels, []) AS dl "
            "WITH DISTINCT dl AS doc_label WHERE doc_label IS NOT NULL AND doc_label <> '' "
            f"MATCH (d) WHERE (d:Document OR d:JiraIssue) AND d.doc_label = doc_label AND {d_filter} "
            "RETURN DISTINCT d.doc_label AS doc_label, "
            "COALESCE(d.file_name, d.issue_key, d.summary, d.doc_id) AS title "
            "UNION "
            f"MATCH (e:Entity) WHERE e.name IN $names AND {ws_filter} "
            "MATCH (e)<-[:MENTIONS]-(d) "
            f"WHERE (d:Document OR d:JiraIssue) AND d.doc_label IS NOT NULL AND {d_filter} "
            "RETURN DISTINCT d.doc_label AS doc_label, "
            "COALESCE(d.file_name, d.issue_key, d.summary, d.doc_id) AS title",
            {"names": entity_names, "ws": workspace_id},
        )
        return [{"doc_label": r["doc_label"], "title": r["title"]} for r in doc_res]


@memgraph_retry()
def delete_document_node(doc_label: str, workspace_id: Optional[str] = None) -> None:
    """Delete a document/issue node and its MENTIONS edges.

    Keeps entity nodes (they may be shared across documents).
    Used during incremental sync before re-ingesting an updated document.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        s.run(
            "MATCH (d) WHERE (d:Document OR d:JiraIssue) "
            "AND d.doc_label = $dl AND d.workspace_id = $ws "
            "DETACH DELETE d",
            {"dl": doc_label, "ws": workspace_id},
        )
    logger.info("graph.delete_document_node", doc_label=doc_label, workspace_id=workspace_id)


@memgraph_retry()
def get_related_documents(texts: List[str],
                          workspace_id: Optional[str] = None) -> List[Dict]:
    """Get documents linked through shared entities."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            doc_res = s.run(
                "MATCH (d1:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d1.raw_text IN $texts "
                "OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity) "
                "WITH COALESCE(alias, e) AS linked "
                "MATCH (linked)<-[:MENTIONS]-(d2:Document) "
                "RETURN DISTINCT d2.doc_id AS doc_id, d2.file_name AS file_name",
                {"texts": texts},
            )
        else:
            doc_res = s.run(
                "MATCH (d1:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d1.raw_text IN $texts AND d1.workspace_id = $ws AND e.workspace_id = $ws "
                "OPTIONAL MATCH (e)-[:ALIAS]-(alias:Entity) WHERE alias.workspace_id = $ws "
                "WITH COALESCE(alias, e) AS linked "
                "MATCH (linked)<-[:MENTIONS]-(d2:Document) WHERE d2.workspace_id = $ws "
                "RETURN DISTINCT d2.doc_id AS doc_id, d2.file_name AS file_name",
                {"texts": texts, "ws": workspace_id},
            )
        return [{"doc_id": r["doc_id"], "file_name": r["file_name"]} for r in doc_res]


@memgraph_retry()
def get_graph_overview(workspace_id: Optional[str] = None,
                       limit: int = 100) -> Dict:
    """Get top-N most connected entities with edges between them.

    Returns nodes sorted by connection count (degree) and all edges
    that exist between the returned nodes.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    limit = max(1, min(limit, 500))
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter = "(e.workspace_id = $ws OR e.workspace_id IS NULL)"
            ws_filter_e1 = "(e1.workspace_id = $ws OR e1.workspace_id IS NULL)"
            ws_filter_e2 = "(e2.workspace_id = $ws OR e2.workspace_id IS NULL)"
        else:
            ws_filter = "e.workspace_id = $ws"
            ws_filter_e1 = "e1.workspace_id = $ws"
            ws_filter_e2 = "e2.workspace_id = $ws"

        # 1. Top-N nodes by degree
        node_res = s.run(
            f"MATCH (e:Entity) WHERE {ws_filter} "
            "OPTIONAL MATCH (e)-[r:RELATION]-() "
            "WITH e, count(r) AS degree "
            "ORDER BY degree DESC LIMIT $lim "
            "RETURN id(e) AS uid, e.name AS name, e.type AS type, "
            "e.workspace_id AS workspace_id, degree",
            {"ws": workspace_id, "lim": limit},
        )
        nodes = []
        node_names: set[str] = set()
        for r in node_res:
            # Skip NULL-workspace nodes that slip through the DEFAULT
            # filter — prevents leaking unassigned entities.
            if r["workspace_id"] is None:
                continue
            nodes.append({
                "id": r["uid"],
                "name": r["name"],
                "type": r["type"],
                "workspace_id": r["workspace_id"],
                "connections": r["degree"],
            })
            node_names.add(r["name"])

        # 2. Edges between returned nodes only
        edges: list[Dict] = []
        if len(node_names) >= 2:
            edge_res = s.run(
                f"MATCH (e1:Entity)-[r:RELATION]->(e2:Entity) "
                f"WHERE {ws_filter_e1} "
                f"AND {ws_filter_e2} "
                "AND e1.name IN $names AND e2.name IN $names "
                "RETURN DISTINCT id(e1) AS source, id(e2) AS target, "
                "r.type AS type, r.valid_from AS valid_from, r.valid_to AS valid_to",
                {"ws": workspace_id, "names": list(node_names)},
            )
            edges = [
                {"source": r["source"], "target": r["target"],
                 "type": r["type"], "valid_from": r["valid_from"],
                 "valid_to": r["valid_to"]}
                for r in edge_res
            ]

    return {"nodes": nodes, "edges": edges, "truncated": len(nodes) >= limit}


@memgraph_retry()
def get_graph_expand(entity_id: int,
                     workspace_id: Optional[str] = None,
                     depth: int = 2,
                     limit: int = 50) -> Dict:
    """Expand a single entity by Memgraph internal ID.

    Args:
        entity_id: Memgraph internal node ID.
        depth: Traversal depth (1-3).
        limit: Max neighbor nodes to return.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(depth, 3))
    limit = max(1, min(limit, 500))
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter_n = "(n.workspace_id = $ws OR n.workspace_id IS NULL)"
            ws_filter_e1 = "(e1.workspace_id = $ws OR e1.workspace_id IS NULL)"
            ws_filter_e2 = "(e2.workspace_id = $ws OR e2.workspace_id IS NULL)"
        else:
            ws_filter_n = "n.workspace_id = $ws"
            ws_filter_e1 = "e1.workspace_id = $ws"
            ws_filter_e2 = "e2.workspace_id = $ws"

        # 1. Find neighbors via RELATION edges up to depth
        node_res = s.run(
            f"MATCH (e:Entity) WHERE id(e) = $eid "
            f"MATCH (e)-[:RELATION*1..{depth}]-(n:Entity) "
            f"WHERE {ws_filter_n} AND id(n) <> $eid "
            "OPTIONAL MATCH (n)-[r:RELATION]-() "
            "WITH DISTINCT n, count(r) AS degree "
            "ORDER BY degree DESC LIMIT $lim "
            "RETURN id(n) AS uid, n.name AS name, n.type AS type, "
            "n.workspace_id AS workspace_id, degree",
            {"eid": entity_id, "ws": workspace_id, "lim": limit},
        )
        nodes = []
        node_ids: set[int] = set()
        for r in node_res:
            # Skip NULL-workspace nodes that slip through the DEFAULT
            # filter — prevents leaking unassigned entities.
            if r["workspace_id"] is None:
                continue
            nodes.append({
                "id": r["uid"],
                "name": r["name"],
                "type": r["type"],
                "workspace_id": r["workspace_id"],
                "connections": r["degree"],
            })
            node_ids.add(r["uid"])

        # Include the center entity itself
        node_ids.add(entity_id)

        # 2. All edges between returned nodes + center
        edges: list[Dict] = []
        if node_ids:
            edge_res = s.run(
                "MATCH (e1:Entity)-[r:RELATION]->(e2:Entity) "
                f"WHERE {ws_filter_e1} AND {ws_filter_e2} "
                "AND id(e1) IN $ids AND id(e2) IN $ids "
                "RETURN DISTINCT id(e1) AS source, id(e2) AS target, "
                "r.type AS type, r.valid_from AS valid_from, r.valid_to AS valid_to",
                {"ids": list(node_ids), "ws": workspace_id},
            )
            edges = [
                {"source": r["source"], "target": r["target"],
                 "type": r["type"], "valid_from": r["valid_from"],
                 "valid_to": r["valid_to"]}
                for r in edge_res
            ]

    return {"nodes": nodes, "edges": edges, "truncated": len(nodes) >= limit}
