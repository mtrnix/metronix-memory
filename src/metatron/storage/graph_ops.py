"""Memgraph graph query/read operations (workspace-aware).

Migrated from PoC: metatron_experiments/metatron/indexers/memgraph_workspace.py

All queries use single-field RETURN for Memgraph 2.18.1 compatibility.
"""
# TODO: async migration
from __future__ import annotations
from typing import Dict, List, Optional

import structlog

from metatron.storage.memgraph import (
    get_memgraph_driver, memgraph_retry, DEFAULT_WORKSPACE_ID, _esc, _esc_list,
)

logger = structlog.get_logger()


def _acl_clause(user_groups: Optional[List[str]], node_alias: str = "d") -> str:
    """Build Cypher WHERE fragment for access_groups filtering.

    Returns empty string when user_groups is None (standalone / no RBAC).
    When user_groups is an empty list, only documents with no access_groups pass.
    """
    if user_groups is None:
        return ""
    if user_groups:
        groups_list = "[" + ", ".join(f"'{_esc(g)}'" for g in user_groups) + "]"
        return (
            f"AND ({node_alias}.access_groups IS NULL "
            f"OR ANY(g IN {node_alias}.access_groups WHERE g IN {groups_list}))"
        )
    return f"AND {node_alias}.access_groups IS NULL"


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


@memgraph_retry()
def get_graph_entities(texts: List[str],
                       workspace_id: Optional[str] = None) -> List[Dict]:
    """Get entities mentioned in documents matching given texts."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        # Step 1: get entities mentioned by matching documents
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                f"WHERE d.raw_text IN {_esc_list(texts)} "
                f"AND (d.workspace_id = {_esc(workspace_id)} "
                "OR d.workspace_id IS NULL) "
                "RETURN DISTINCT e",
            )
        else:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                f"WHERE d.raw_text IN {_esc_list(texts)} "
                f"AND d.workspace_id = {_esc(workspace_id)} "
                f"AND e.workspace_id = {_esc(workspace_id)} "
                "RETURN DISTINCT e",
            )
        entities = []
        for r in ent_res:
            node = r[0]
            entities.append({
                "name": node.get("name"),
                "type": node.get("type"),
            })

        # Step 2: get aliases for each entity
        result = []
        for ent in entities:
            name = ent["name"]
            if not name:
                continue
            if workspace_id == DEFAULT_WORKSPACE_ID:
                alias_res = s.run(
                    f"MATCH (e:Entity)-[:ALIAS]-(alias:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    "RETURN alias",
                )
            else:
                alias_res = s.run(
                    f"MATCH (e:Entity)-[:ALIAS]-(alias:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_esc(workspace_id)} "
                    f"AND alias.workspace_id = {_esc(workspace_id)} "
                    "RETURN alias",
                )
            aliases = []
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    aliases.append(aname)
            result.append({
                "name": name,
                "type": ent["type"],
                "aliases": aliases,
            })
        return result


@memgraph_retry()
def get_entities_by_doc_labels(doc_labels: List[str],
                               workspace_id: Optional[str] = None,
                               ) -> List[Dict]:
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
                f"AND d.doc_label IN {_esc_list(labels)} "
                f"AND (d.workspace_id = {_esc(workspace_id)} "
                "OR d.workspace_id IS NULL) "
                "MATCH (d)-[:MENTIONS]->(e:Entity) "
                "RETURN DISTINCT e",
            )
        else:
            ent_res = s.run(
                "MATCH (d) WHERE (d:Document OR d:JiraIssue) "
                f"AND d.doc_label IN {_esc_list(labels)} "
                f"AND d.workspace_id = {_esc(workspace_id)} "
                "MATCH (d)-[:MENTIONS]->(e:Entity) "
                f"WHERE e.workspace_id = {_esc(workspace_id)} "
                "RETURN DISTINCT e",
            )
        entities = []
        for r in ent_res:
            node = r[0]
            entities.append({
                "name": node.get("name"),
                "type": node.get("type"),
            })

        # Get aliases for each entity
        result = []
        for ent in entities:
            name = ent["name"]
            if not name:
                continue
            if workspace_id == DEFAULT_WORKSPACE_ID:
                alias_res = s.run(
                    f"MATCH (e:Entity)-[:ALIAS]-(alias:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    "RETURN alias",
                )
            else:
                alias_res = s.run(
                    f"MATCH (e:Entity)-[:ALIAS]-(alias:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_esc(workspace_id)} "
                    f"AND alias.workspace_id = {_esc(workspace_id)} "
                    "RETURN alias",
                )
            aliases = []
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    aliases.append(aname)
            result.append({
                "name": name,
                "type": ent["type"],
                "aliases": aliases,
            })
        return result


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
                f"WHERE e.workspace_id = {_esc(workspace_id)} "
                "OR e.workspace_id IS NULL "
                "RETURN DISTINCT e "
                f"LIMIT {_esc(limit)}",
            )
        else:
            res = s.run(
                f"MATCH (e:Entity) WHERE e.workspace_id = {_esc(workspace_id)} "
                "RETURN DISTINCT e "
                f"LIMIT {_esc(limit)}",
            )
        return [{"name": r[0].get("name"), "type": r[0].get("type")}
                for r in res]


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
    driver = get_memgraph_driver()
    results: list[Dict] = []
    seen: set[tuple] = set()
    with driver.session() as s:
        # For each entity, get RELATION edges (both directions)
        for name in entity_names:
            _all_rels = []
            if workspace_id == DEFAULT_WORKSPACE_ID:
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} RETURN r",
                ))
            else:
                _ws = _esc(workspace_id)
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND e2.workspace_id = {_ws} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND e2.workspace_id = {_ws} RETURN r",
                ))
            for rr in _all_rels:
                rel = rr[0]
                src_node = rel.start_node
                tgt_node = rel.end_node
                src_name = src_node.get("name", "")
                tgt_name = tgt_node.get("name", "")
                rel_type = rel.get("type")
                vf = rel.get("valid_from")
                vt = rel.get("valid_to")
                if active_only and vt is not None:
                    continue
                key = (src_name, tgt_name, rel_type)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "source": src_name,
                    "target": tgt_name,
                    "type": rel_type,
                    "valid_from": vf,
                    "valid_to": vt,
                })
            if len(results) >= 200:
                break
    return results[:200]


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
    driver = get_memgraph_driver()
    results: list[Dict] = []
    seen: set[tuple] = set()
    with driver.session() as s:
        for name in entity_names:
            _all_rels = []
            if workspace_id == DEFAULT_WORKSPACE_ID:
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} RETURN r",
                ))
            else:
                _ws = _esc(workspace_id)
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND e2.workspace_id = {_ws} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(e2:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND e2.workspace_id = {_ws} RETURN r",
                ))
            for rr in _all_rels:
                rel = rr[0]
                vf = rel.get("valid_from")
                vt = rel.get("valid_to")
                # Date filter in Python
                if vf is not None and vf > target_date:
                    continue
                if vt is not None and vt < target_date:
                    continue
                src_name = rel.start_node.get("name", "")
                tgt_name = rel.end_node.get("name", "")
                rel_type = rel.get("type")
                key = (src_name, tgt_name, rel_type)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "source": src_name,
                    "target": tgt_name,
                    "type": rel_type,
                    "valid_from": vf,
                    "valid_to": vt,
                })
            if len(results) >= 200:
                break
    return results[:200]


@memgraph_retry()
def get_doc_labels_by_entities(entity_names: List[str],
                               workspace_id: Optional[str] = None,
                               user_groups: Optional[List[str]] = None,
                               ) -> List[Dict]:
    """Get document labels for documents linked to given entities."""
    if not entity_names:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    results: list[Dict] = []
    seen_labels: set[str] = set()
    with driver.session() as s:
        ws = _esc(workspace_id)
        for name in entity_names:
            # Path 1: via doc_labels property
            ent_res = s.run(
                f"MATCH (e:Entity) "
                f"WHERE e.name = {_esc(name)} "
                f"AND e.workspace_id = {ws} "
                "RETURN e",
            )
            for er in ent_res:
                node = er[0]
                doc_labels = node.get("doc_labels")
                if not doc_labels:
                    continue
                for dl in doc_labels:
                    if dl and dl not in seen_labels:
                        seen_labels.add(dl)

            # Path 2: via MENTIONS edges
            if workspace_id == DEFAULT_WORKSPACE_ID:
                d_filter = (
                    f"(d.workspace_id = {ws} "
                    "OR d.workspace_id IS NULL)"
                )
            else:
                d_filter = f"d.workspace_id = {ws}"
            acl = _acl_clause(user_groups, "d")
            doc_res = s.run(
                "MATCH (e:Entity)<-[:MENTIONS]-(d) "
                f"WHERE e.name = {_esc(name)} "
                f"AND e.workspace_id = {ws} "
                "AND (d:Document OR d:JiraIssue) "
                f"AND d.doc_label IS NOT NULL AND {d_filter} "
                f"{acl} "
                "RETURN d",
            )
            for dr in doc_res:
                dnode = dr[0]
                dl = dnode.get("doc_label")
                if dl and dl not in seen_labels:
                    seen_labels.add(dl)

        # Fetch titles for all doc_labels
        acl = _acl_clause(user_groups, "d")
        for dl in seen_labels:
            d_res = s.run(
                "MATCH (d) WHERE (d:Document OR d:JiraIssue) "
                f"AND d.doc_label = {_esc(dl)} "
                f"{acl} "
                "RETURN d",
            )
            rec = d_res.single()
            if rec:
                dnode = rec[0]
                title = (
                    dnode.get("file_name")
                    or dnode.get("issue_key")
                    or dnode.get("summary")
                    or dnode.get("doc_id")
                )
                results.append({"doc_label": dl, "title": title})
    return results


@memgraph_retry()
def delete_document_node(doc_label: str,
                         workspace_id: Optional[str] = None) -> None:
    """Delete a document/issue node and its MENTIONS edges.

    Keeps entity nodes (they may be shared across documents).
    Used during incremental sync before re-ingesting an updated document.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        s.run(
            "MATCH (d) WHERE (d:Document OR d:JiraIssue) "
            f"AND d.doc_label = {_esc(doc_label)} "
            f"AND d.workspace_id = {_esc(workspace_id)} "
            "DETACH DELETE d",
        )
    logger.info("graph.delete_document_node",
                doc_label=doc_label, workspace_id=workspace_id)


@memgraph_retry()
def get_related_documents(texts: List[str],
                          workspace_id: Optional[str] = None,
                          user_groups: Optional[List[str]] = None,
                          ) -> List[Dict]:
    """Get documents linked through shared entities."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        # Step 1: get entities mentioned by matching documents
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d1:Document)-[:MENTIONS]->(e:Entity) "
                f"WHERE d1.raw_text IN {_esc_list(texts)} "
                "RETURN DISTINCT e",
            )
        else:
            ent_res = s.run(
                "MATCH (d1:Document)-[:MENTIONS]->(e:Entity) "
                f"WHERE d1.raw_text IN {_esc_list(texts)} "
                f"AND d1.workspace_id = {_esc(workspace_id)} "
                f"AND e.workspace_id = {_esc(workspace_id)} "
                "RETURN DISTINCT e",
            )
        entity_names: set[str] = set()
        for r in ent_res:
            name = r[0].get("name")
            if name:
                entity_names.add(name)

        # Step 2: also collect alias names
        expanded_names = set(entity_names)
        for name in entity_names:
            if workspace_id == DEFAULT_WORKSPACE_ID:
                alias_res = s.run(
                    f"MATCH (e:Entity)-[:ALIAS]-(alias:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    "RETURN alias",
                )
            else:
                alias_res = s.run(
                    f"MATCH (e:Entity)-[:ALIAS]-(alias:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND alias.workspace_id = {_esc(workspace_id)} "
                    "RETURN alias",
                )
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    expanded_names.add(aname)

        # Step 3: find documents mentioning those entities
        acl = _acl_clause(user_groups, "d2")
        results: list[Dict] = []
        seen: set[str] = set()
        for ename in expanded_names:
            if workspace_id == DEFAULT_WORKSPACE_ID:
                doc_res = s.run(
                    f"MATCH (ent:Entity)<-[:MENTIONS]-(d2:Document) "
                    f"WHERE ent.name = {_esc(ename)} "
                    f"{acl} "
                    "RETURN d2",
                )
            else:
                doc_res = s.run(
                    f"MATCH (ent:Entity)<-[:MENTIONS]-(d2:Document) "
                    f"WHERE ent.name = {_esc(ename)} "
                    f"AND d2.workspace_id = {_esc(workspace_id)} "
                    f"{acl} "
                    "RETURN d2",
                )
            for dr in doc_res:
                dnode = dr[0]
                doc_id = dnode.get("doc_id")
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    results.append({
                        "doc_id": doc_id,
                        "file_name": dnode.get("file_name"),
                    })
        return results


@memgraph_retry()
def get_graph_overview(workspace_id: Optional[str] = None,
                       limit: int = 100,
                       user_groups: Optional[List[str]] = None) -> Dict:
    """Get top-N most connected entities with edges between them.

    Returns nodes sorted by connection count (degree) and all edges
    that exist between the returned nodes.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    limit = max(1, min(limit, 500))
    driver = get_memgraph_driver()
    with driver.session() as s:
        _ws = _esc(workspace_id)
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter = (
                f"(a.workspace_id = {_ws} "
                "OR a.workspace_id IS NULL)"
            )
        else:
            ws_filter = f"a.workspace_id = {_ws}"

        # 1. Get all edges for workspace in ONE query
        q_edges = (
            f"MATCH (a:Entity)-[r]->(b:Entity) "
            f"WHERE {ws_filter} "
            "RETURN r"
        )
        logger.debug("graph_overview.edges", query=q_edges)
        all_edges: list[Dict] = []
        node_map: dict[int, Dict] = {}  # id → node dict
        try:
            for rec in s.run(q_edges):
                rel = rec[0]
                src_node = rel.start_node
                tgt_node = rel.end_node
                src_id = src_node.id
                tgt_id = tgt_node.id
                # Collect nodes from edges
                if src_id not in node_map:
                    ws = src_node.get("workspace_id")
                    if ws is not None:
                        node_map[src_id] = {
                            "id": src_id,
                            "name": src_node.get("name", ""),
                            "type": src_node.get("type"),
                            "workspace_id": ws,
                        }
                if tgt_id not in node_map:
                    ws = tgt_node.get("workspace_id")
                    if ws is not None:
                        node_map[tgt_id] = {
                            "id": tgt_id,
                            "name": tgt_node.get("name", ""),
                            "type": tgt_node.get("type"),
                            "workspace_id": ws,
                        }
                all_edges.append({
                    "source": src_id,
                    "target": tgt_id,
                    "type": rel.get("type"),
                    "valid_from": rel.get("valid_from"),
                    "valid_to": rel.get("valid_to"),
                })
        except Exception as exc:
            logger.warning("graph_overview.edges_failed", error=str(exc))

        # Also fetch isolated nodes (no edges)
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter_e = (
                f"(e.workspace_id = {_ws} "
                "OR e.workspace_id IS NULL)"
            )
        else:
            ws_filter_e = f"e.workspace_id = {_ws}"
        q_nodes = f"MATCH (e:Entity) WHERE {ws_filter_e} RETURN e"
        logger.debug("graph_overview.nodes", query=q_nodes)
        for rec in s.run(q_nodes):
            node = rec[0]
            nid = node.id
            if nid not in node_map:
                ws = node.get("workspace_id")
                if ws is not None:
                    node_map[nid] = {
                        "id": nid,
                        "name": node.get("name", ""),
                        "type": node.get("type"),
                        "workspace_id": ws,
                    }

        # 2. Compute degree from edges in Python
        degree: dict[int, int] = {}
        for e in all_edges:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1

        # 3. Sort by degree, take top-N
        ent_list = list(node_map.values())
        for ent in ent_list:
            ent["connections"] = degree.get(ent["id"], 0)
        ent_list.sort(key=lambda x: x["connections"], reverse=True)
        nodes = ent_list[:limit]

        node_ids: set[int] = {n["id"] for n in nodes}

        # 4. Filter edges to only those between returned nodes
        edges: list[Dict] = []
        seen_edges: set[tuple] = set()
        for e in all_edges:
            if e["source"] in node_ids and e["target"] in node_ids:
                key = (e["source"], e["target"], e["type"])
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(e)

    return {
        "nodes": nodes, "edges": edges,
        "truncated": len(nodes) >= limit,
    }


@memgraph_retry()
def get_graph_expand(entity_id: int,
                     workspace_id: Optional[str] = None,
                     depth: int = 2,
                     limit: int = 50,
                     user_groups: Optional[List[str]] = None) -> Dict:
    """Expand a single entity by Memgraph internal ID.

    Uses the same single-query approach as get_graph_overview:
    fetch ALL workspace edges once, then find neighbors of entity_id
    by walking edges in Python up to *depth* hops.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(depth, 3))
    limit = max(1, min(limit, 500))
    driver = get_memgraph_driver()
    with driver.session() as s:
        _ws = _esc(workspace_id)

        # 1. Fetch ALL edges for workspace in one query
        q_edges = (
            f"MATCH (a:Entity)-[r]->(b:Entity) "
            f"WHERE a.workspace_id = {_ws} "
            "RETURN r"
        )
        logger.debug("graph_expand.edges", query=q_edges)

        all_edges: list[Dict] = []
        node_map: dict[int, Dict] = {}  # id → node dict
        # adjacency: node_id → set of neighbor node_ids
        adj: dict[int, set[int]] = {}
        try:
            for rec in s.run(q_edges):
                rel = rec[0]
                src_node = rel.start_node
                tgt_node = rel.end_node
                src_id = src_node.id
                tgt_id = tgt_node.id
                # Collect nodes
                for nd, nid in ((src_node, src_id), (tgt_node, tgt_id)):
                    if nid not in node_map:
                        ws = nd.get("workspace_id")
                        if ws is not None:
                            node_map[nid] = {
                                "id": nid,
                                "name": nd.get("name", ""),
                                "type": nd.get("type"),
                                "workspace_id": ws,
                            }
                # Build adjacency (both directions for traversal)
                adj.setdefault(src_id, set()).add(tgt_id)
                adj.setdefault(tgt_id, set()).add(src_id)
                all_edges.append({
                    "source": src_id,
                    "target": tgt_id,
                    "type": rel.get("type"),
                    "valid_from": rel.get("valid_from"),
                    "valid_to": rel.get("valid_to"),
                })
        except Exception as exc:
            logger.warning("graph_expand.edges_failed", error=str(exc))
            return {"nodes": [], "edges": [], "truncated": False}

        # 2. BFS from entity_id up to depth hops (in Python)
        visited: set[int] = {entity_id}
        frontier: set[int] = {entity_id}
        for _ in range(depth):
            next_frontier: set[int] = set()
            for nid in frontier:
                for neighbor in adj.get(nid, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break

        # Remove center from neighbor list (it's included separately)
        neighbor_ids = visited - {entity_id}

        # 3. Compute degree from edges, sort, take top-N
        degree: dict[int, int] = {}
        for e in all_edges:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1

        neighbor_list = []
        for nid in neighbor_ids:
            if nid in node_map:
                nd = dict(node_map[nid])
                nd["connections"] = degree.get(nid, 0)
                neighbor_list.append(nd)
        neighbor_list.sort(key=lambda x: x["connections"], reverse=True)
        nodes = neighbor_list[:limit]

        final_ids: set[int] = {entity_id}
        for n in nodes:
            final_ids.add(n["id"])

        # 4. Filter edges to final node set, deduplicate
        edges: list[Dict] = []
        seen_edges: set[tuple] = set()
        for e in all_edges:
            if e["source"] in final_ids and e["target"] in final_ids:
                key = (e["source"], e["target"], e["type"])
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(e)

    return {
        "nodes": nodes, "edges": edges,
        "truncated": len(nodes) >= limit,
    }
