"""Memgraph graph query/read operations (workspace-aware).

Migrated from PoC: metatron_experiments/metatron/indexers/memgraph_workspace.py

All queries use single-field RETURN for Memgraph 2.18.1 compatibility.

Memgraph 2.18.1 + neo4j driver 5.28 Cypher constraints:
- Variable names must NOT contain digits (e2, d1 → parser errors)
- Second-node variables after -[r]->() must be single-char (a, b, n — not tgt)
- Relationship types that collide with keyword prefixes (ALIAS→ALL,
  RELATION→RETURN) need backtick-escaping or type(r) filtering
- Use ``type(r) = 'TYPE'`` in WHERE as a safe alternative to ``[:TYPE]``
"""
# TODO: async migration
from __future__ import annotations

import structlog

from metatron.storage.memgraph import (
    DEFAULT_WORKSPACE_ID,
    _esc,
    _esc_list,
    get_memgraph_driver,
    memgraph_retry,
)

logger = structlog.get_logger()


def _alias_query(entity_name: str, workspace_id: str | None = None,
                  ws_esc: str | None = None) -> str:
    """Build Cypher query for ALIAS edges in both directions.

    ``ALIAS`` is a reserved keyword in Memgraph, so we avoid it in MATCH
    patterns entirely.  Instead we match generic edges and filter by
    ``type(r) = 'ALIAS'`` in the WHERE clause.
    """
    name = _esc(entity_name)
    if workspace_id is None or workspace_id == DEFAULT_WORKSPACE_ID:
        return (
            f"MATCH (e:Entity)-[r]->(n:Entity) "
            f"WHERE type(r) = 'ALIAS' AND e.name = {name} RETURN n "
            f"UNION "
            f"MATCH (e:Entity)<-[r]-(n:Entity) "
            f"WHERE type(r) = 'ALIAS' AND e.name = {name} RETURN n"
        )
    ws = ws_esc or _esc(workspace_id)
    return (
        f"MATCH (e:Entity)-[r]->(n:Entity) "
        f"WHERE type(r) = 'ALIAS' AND e.name = {name} "
        f"AND e.workspace_id = {ws} "
        f"AND n.workspace_id = {ws} RETURN n "
        f"UNION "
        f"MATCH (e:Entity)<-[r]-(n:Entity) "
        f"WHERE type(r) = 'ALIAS' AND e.name = {name} "
        f"AND e.workspace_id = {ws} "
        f"AND n.workspace_id = {ws} RETURN n"
    )


@memgraph_retry()
def resolve_transitive_aliases(
    entity_name: str,
    workspace_id: str | None = None,
    max_hops: int = 3,
) -> set[str]:
    """Resolve all aliases reachable within max_hops ALIAS edges.

    BFS traversal using _alias_query() per hop.
    Returns set of all equivalent names (including input).
    Handles cycles (bidirectional ALIAS edges).
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    visited: set[str] = {entity_name}
    frontier: set[str] = {entity_name}
    driver = get_memgraph_driver()
    with driver.session() as s:
        for _ in range(max_hops):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for name in frontier:
                alias_res = s.run(_alias_query(name, workspace_id))
                for ar in alias_res:
                    aname = ar[0].get("name")
                    if aname and aname not in visited:
                        visited.add(aname)
                        next_frontier.add(aname)
            frontier = next_frontier
    return visited


def resolve_entity_aliases_batch(
    entity_names: list[str],
    workspace_id: str | None = None,
    max_hops: int = 3,
) -> dict[str, set[str]]:
    """Resolve transitive aliases for multiple entities."""
    if not entity_names:
        return {}
    return {
        name: resolve_transitive_aliases(name, workspace_id, max_hops)
        for name in entity_names
    }


def _acl_clause(user_groups: list[str] | None, node_alias: str = "d") -> str:
    """Build Cypher WHERE fragment for access_groups filtering.

    Returns empty string when user_groups is None (standalone / no RBAC).
    When user_groups is an empty list, only documents with no access_groups pass.
    """
    if user_groups is None:
        return ""
    if user_groups:
        groups_list = _esc_list(user_groups)
        return (
            f"AND ({node_alias}.`access_groups` IS NULL "
            f"OR ANY(g IN {node_alias}.`access_groups` WHERE g IN {groups_list}))"
        )
    return f"AND {node_alias}.`access_groups` IS NULL"


def _normalize_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


@memgraph_retry()
def get_graph_entities(texts: list[str],
                       workspace_id: str | None = None) -> list[dict]:
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
            alias_res = s.run(_alias_query(name, workspace_id))
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
def get_entities_by_doc_labels(doc_labels: list[str],
                               workspace_id: str | None = None,
                               ) -> list[dict]:
    """Get entities mentioned in documents by doc_label."""
    labels = [l for l in doc_labels if l]
    if not labels:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
                f"AND d.doc_label IN {_esc_list(labels)} "
                f"AND (d.workspace_id = {_esc(workspace_id)} "
                "OR d.workspace_id IS NULL) "
                "MATCH (d)-[:MENTIONS]->(e:Entity) "
                "RETURN DISTINCT e",
            )
        else:
            ent_res = s.run(
                "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
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
            alias_res = s.run(_alias_query(name, workspace_id))
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
def get_all_workspace_entities(workspace_id: str | None = None,
                               limit: int = 100) -> list[dict]:
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
def get_graph_relationships(
    entity_names: list[str],
    workspace_id: str | None = None,
    max_depth: int = 5,
    active_only: bool = False,
    valid_after: str | None = None,
    valid_before: str | None = None,
) -> list[dict]:
    """Get relationships for entities (variable depth traversal).

    Args:
        active_only: When True, only return relationships where valid_to IS NULL
                     (i.e. currently active / not closed).
        valid_after: ISO date string — only return relationships with
                     valid_from >= this value (NULL valid_from included).
        valid_before: ISO date string — only return relationships with
                      valid_from <= this value (NULL valid_from included).
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(max_depth, 5))
    driver = get_memgraph_driver()
    results: list[dict] = []
    seen: set[tuple] = set()

    # Build optional temporal WHERE fragments
    temporal = ""
    if active_only:
        temporal += " AND r.valid_to IS NULL"
    if valid_after is not None:
        temporal += (
            f" AND (r.valid_from IS NULL OR r.valid_from >= {_esc(valid_after)})"
        )
    if valid_before is not None:
        temporal += (
            f" AND (r.valid_from IS NULL OR r.valid_from <= {_esc(valid_before)})"
        )

    with driver.session() as s:
        # For each entity, get RELATION edges (both directions)
        for name in entity_names:
            _all_rels = []
            if workspace_id == DEFAULT_WORKSPACE_ID:
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(b:Entity) "
                    f"WHERE e.name = {_esc(name)}"
                    f"{temporal} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(b:Entity) "
                    f"WHERE e.name = {_esc(name)}"
                    f"{temporal} RETURN r",
                ))
            else:
                _ws = _esc(workspace_id)
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(b:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND b.workspace_id = {_ws}"
                    f"{temporal} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(b:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND b.workspace_id = {_ws}"
                    f"{temporal} RETURN r",
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
def get_relationships_at_date(entity_names: list[str],
                              target_date: str,
                              workspace_id: str | None = None,
                              max_depth: int = 5) -> list[dict]:
    """Get relationships valid at a specific date (ISO format YYYY-MM-DD).

    Temporal filtering is pushed into Cypher WHERE clauses so Memgraph
    can prune early instead of returning all edges for Python post-filter.

    Returns relationships where:
    - valid_from is NULL or <= target_date
    - valid_to is NULL or >= target_date
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    results: list[dict] = []
    seen: set[tuple] = set()
    _td = _esc(target_date)
    temporal = (
        f" AND (r.valid_from IS NULL OR r.valid_from <= {_td})"
        f" AND (r.valid_to IS NULL OR r.valid_to >= {_td})"
    )
    with driver.session() as s:
        for name in entity_names:
            _all_rels = []
            if workspace_id == DEFAULT_WORKSPACE_ID:
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(b:Entity) "
                    f"WHERE e.name = {_esc(name)}"
                    f"{temporal} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(b:Entity) "
                    f"WHERE e.name = {_esc(name)}"
                    f"{temporal} RETURN r",
                ))
            else:
                _ws = _esc(workspace_id)
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)-[r]->(b:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND b.workspace_id = {_ws}"
                    f"{temporal} RETURN r",
                ))
                _all_rels.extend(s.run(
                    f"MATCH (e:Entity)<-[r]-(b:Entity) "
                    f"WHERE e.name = {_esc(name)} "
                    f"AND e.workspace_id = {_ws} "
                    f"AND b.workspace_id = {_ws}"
                    f"{temporal} RETURN r",
                ))
            for rr in _all_rels:
                rel = rr[0]
                src_name = rel.start_node.get("name", "")
                tgt_name = rel.end_node.get("name", "")
                rel_type = rel.get("type")
                vf = rel.get("valid_from")
                vt = rel.get("valid_to")
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
def get_doc_labels_by_entities(entity_names: list[str],
                               workspace_id: str | None = None,
                               user_groups: list[str] | None = None,
                               ) -> list[dict]:
    """Get document labels for documents linked to given entities."""
    if not entity_names:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    results: list[dict] = []
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
                "AND ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
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
                "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
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
                         workspace_id: str | None = None) -> None:
    """Delete a document/issue node and its MENTIONS edges.

    Keeps entity nodes (they may be shared across documents).
    Used during incremental sync before re-ingesting an updated document.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        s.run(
            "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
            f"AND d.doc_label = {_esc(doc_label)} "
            f"AND d.workspace_id = {_esc(workspace_id)} "
            "DETACH DELETE d",
        )
    logger.info("graph.delete_document_node",
                doc_label=doc_label, workspace_id=workspace_id)


@memgraph_retry()
def get_related_documents(texts: list[str],
                          workspace_id: str | None = None,
                          user_groups: list[str] | None = None,
                          ) -> list[dict]:
    """Get documents linked through shared entities."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_memgraph_driver()
    with driver.session() as s:
        # Step 1: get entities mentioned by matching documents
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                f"WHERE d.raw_text IN {_esc_list(texts)} "
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
        entity_names: set[str] = set()
        for r in ent_res:
            name = r[0].get("name")
            if name:
                entity_names.add(name)

        # Step 2: also collect alias names
        expanded_names = set(entity_names)
        for name in entity_names:
            alias_res = s.run(_alias_query(name, workspace_id))
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    expanded_names.add(aname)

        # Step 3: find documents mentioning those entities
        acl = _acl_clause(user_groups, "m")
        results: list[dict] = []
        seen: set[str] = set()
        for ename in expanded_names:
            if workspace_id == DEFAULT_WORKSPACE_ID:
                doc_res = s.run(
                    f"MATCH (ent:Entity)<-[:MENTIONS]-(m:Document) "
                    f"WHERE ent.name = {_esc(ename)} "
                    f"{acl} "
                    "RETURN m",
                )
            else:
                doc_res = s.run(
                    f"MATCH (ent:Entity)<-[:MENTIONS]-(m:Document) "
                    f"WHERE ent.name = {_esc(ename)} "
                    f"AND m.workspace_id = {_esc(workspace_id)} "
                    f"{acl} "
                    "RETURN m",
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
def get_graph_overview(workspace_id: str | None = None,
                       limit: int = 100,
                       user_groups: list[str] | None = None) -> dict:
    """Get top-N most connected entities with edges between them.

    Returns nodes sorted by connection count (degree) and all edges
    that exist between the returned nodes.

    Note: user_groups is accepted for API consistency but not used here.
    This function queries Entity→Entity edges only (no Document nodes).
    Entity-level ACL filtering would require a different approach since
    entities are shared across documents.
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
            "RETURN a, r, b"
        )
        logger.debug("graph_overview.edges", query=q_edges)
        all_edges: list[dict] = []
        node_map: dict[int, dict] = {}  # id → node dict
        try:
            for rec in s.run(q_edges):
                src_node = rec[0]
                rel = rec[1]
                tgt_node = rec[2]
                src_id = src_node.id
                tgt_id = tgt_node.id
                # Collect nodes from edges (full properties via explicit RETURN)
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
        edges: list[dict] = []
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
                     workspace_id: str | None = None,
                     depth: int = 2,
                     limit: int = 50,
                     user_groups: list[str] | None = None) -> dict:
    """Expand a single entity by Memgraph internal ID.

    Uses the same single-query approach as get_graph_overview:
    fetch ALL workspace edges once, then find neighbors of entity_id
    by walking edges in Python up to *depth* hops.

    Note: user_groups is accepted for API consistency but not used here.
    This function queries Entity→Entity edges only (no Document nodes).
    Entity-level ACL filtering would require a different approach since
    entities are shared across documents.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(depth, 3))
    limit = max(1, min(limit, 500))
    driver = get_memgraph_driver()
    with driver.session() as s:
        _ws = _esc(workspace_id)

        # 1. Fetch ALL edges for workspace in one query
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter = (
                f"(a.workspace_id = {_ws} "
                "OR a.workspace_id IS NULL)"
            )
        else:
            ws_filter = f"a.workspace_id = {_ws}"
        q_edges = (
            f"MATCH (a:Entity)-[r]->(b:Entity) "
            f"WHERE {ws_filter} "
            "RETURN a, r, b"
        )
        logger.debug("graph_expand.edges", query=q_edges)

        all_edges: list[dict] = []
        node_map: dict[int, dict] = {}  # id → node dict
        # adjacency: node_id → set of neighbor node_ids
        adj: dict[int, set[int]] = {}
        try:
            for rec in s.run(q_edges):
                src_node = rec[0]
                rel = rec[1]
                tgt_node = rec[2]
                src_id = src_node.id
                tgt_id = tgt_node.id
                # Collect nodes (full properties from explicit RETURN)
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
        edges: list[dict] = []
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
