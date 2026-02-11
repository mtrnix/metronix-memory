"""Memgraph graph query/read operations (workspace-aware).

Migrated from PoC: metatron_experiments/metatron/indexers/memgraph_workspace.py
"""
# TODO: async migration
from __future__ import annotations
from typing import Dict, List, Optional

import structlog

from metatron.storage.memgraph import get_memgraph_driver, DEFAULT_WORKSPACE_ID

logger = structlog.get_logger()


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


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


def get_graph_relationships(entity_names: List[str],
                            workspace_id: Optional[str] = None,
                            max_depth: int = 5) -> List[Dict]:
    """Get relationships for entities (variable depth traversal)."""
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(max_depth, 5))
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            rel_res = s.run(
                f"MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity) "
                "WHERE e.name IN $names "
                "UNWIND range(0, size(rels)-1) AS idx "
                "WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2 "
                "WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL "
                "RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type "
                "LIMIT 200",
                {"names": entity_names},
            )
        else:
            rel_res = s.run(
                f"MATCH p = (e:Entity)-[rels:RELATION*1..{depth}]-(e2:Entity) "
                "WHERE e.name IN $names AND e.workspace_id = $ws AND e2.workspace_id = $ws "
                "UNWIND range(0, size(rels)-1) AS idx "
                "WITH rels[idx] AS r, nodes(p)[idx] AS n1, nodes(p)[idx+1] AS n2 "
                "WHERE n1.name IS NOT NULL AND n2.name IS NOT NULL "
                "RETURN DISTINCT n1.name AS source, n2.name AS target, r.type AS rel_type "
                "LIMIT 200",
                {"names": entity_names, "ws": workspace_id},
            )
        return [{"source": r["source"], "target": r["target"],
                 "type": r["rel_type"]} for r in rel_res]


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
