"""Graph query/read operations (workspace-aware).

All queries use Neo4j parameterized queries ($param) over the neo4j Python driver.
"""

from __future__ import annotations

import structlog

from metatron.storage.neo4j_graph import (
    DEFAULT_WORKSPACE_ID,
    get_graph_driver,
    graph_retry,
)

logger = structlog.get_logger()


def _alias_query(entity_name: str, workspace_id: str | None = None) -> tuple[str, dict]:
    """Build Cypher query + params for ALIAS edges in both directions."""
    params: dict = {"name": entity_name}
    if workspace_id is None or workspace_id == DEFAULT_WORKSPACE_ID:
        query = (
            "MATCH (e:Entity)-[:ALIAS]->(n:Entity) "
            "WHERE e.name = $name RETURN n "
            "UNION "
            "MATCH (e:Entity)<-[:ALIAS]-(n:Entity) "
            "WHERE e.name = $name RETURN n"
        )
    else:
        params["ws"] = workspace_id
        query = (
            "MATCH (e:Entity)-[:ALIAS]->(n:Entity) "
            "WHERE e.name = $name "
            "AND e.workspace_id = $ws "
            "AND n.workspace_id = $ws RETURN n "
            "UNION "
            "MATCH (e:Entity)<-[:ALIAS]-(n:Entity) "
            "WHERE e.name = $name "
            "AND e.workspace_id = $ws "
            "AND n.workspace_id = $ws RETURN n"
        )
    return query, params


@graph_retry()
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
    driver = get_graph_driver()
    with driver.session() as s:
        for _ in range(max_hops):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for name in frontier:
                query, params = _alias_query(name, workspace_id)
                alias_res = s.run(query, params)
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
        name: resolve_transitive_aliases(name, workspace_id, max_hops) for name in entity_names
    }


def _acl_clause(
    user_groups: list[str] | None,
    node_alias: str = "d",
) -> tuple[str, dict]:
    """Build Cypher WHERE fragment + params for access_groups filtering.

    Returns (fragment, params_dict).
    Empty string and empty dict when user_groups is None (standalone / no RBAC).
    When user_groups is an empty list, only documents with no access_groups pass.
    """
    if user_groups is None:
        return "", {}
    if user_groups:
        return (
            f"AND ({node_alias}.access_groups IS NULL "
            f"OR ANY(g IN {node_alias}.access_groups WHERE g IN $user_groups))",
            {"user_groups": user_groups},
        )
    return f"AND {node_alias}.access_groups IS NULL", {}


def _normalize_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


@graph_retry()
def get_graph_entities(texts: list[str], workspace_id: str | None = None) -> list[dict]:
    """Get entities mentioned in documents matching given texts."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d.raw_text IN $texts "
                "AND (d.workspace_id = $ws "
                "OR d.workspace_id IS NULL) "
                "RETURN DISTINCT e",
                {"texts": texts, "ws": workspace_id},
            )
        else:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d.raw_text IN $texts "
                "AND d.workspace_id = $ws "
                "AND e.workspace_id = $ws "
                "RETURN DISTINCT e",
                {"texts": texts, "ws": workspace_id},
            )
        entities = []
        for r in ent_res:
            node = r[0]
            entities.append(
                {
                    "name": node.get("name"),
                    "type": node.get("type"),
                }
            )

        result = []
        for ent in entities:
            name = ent["name"]
            if not name:
                continue
            query, params = _alias_query(name, workspace_id)
            alias_res = s.run(query, params)
            aliases = []
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    aliases.append(aname)
            result.append(
                {
                    "name": name,
                    "type": ent["type"],
                    "aliases": aliases,
                }
            )
        return result


@graph_retry()
def get_entities_by_doc_labels(
    doc_labels: list[str],
    workspace_id: str | None = None,
) -> list[dict]:
    """Get entities mentioned in documents by doc_label."""
    labels = [l for l in doc_labels if l]
    if not labels:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
                "AND d.doc_label IN $labels "
                "AND (d.workspace_id = $ws "
                "OR d.workspace_id IS NULL) "
                "MATCH (d)-[:MENTIONS]->(e:Entity) "
                "RETURN DISTINCT e",
                {"labels": labels, "ws": workspace_id},
            )
        else:
            ent_res = s.run(
                "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
                "AND d.doc_label IN $labels "
                "AND d.workspace_id = $ws "
                "MATCH (d)-[:MENTIONS]->(e:Entity) "
                "WHERE e.workspace_id = $ws "
                "RETURN DISTINCT e",
                {"labels": labels, "ws": workspace_id},
            )
        entities = []
        for r in ent_res:
            node = r[0]
            entities.append(
                {
                    "name": node.get("name"),
                    "type": node.get("type"),
                }
            )

        result = []
        for ent in entities:
            name = ent["name"]
            if not name:
                continue
            query, params = _alias_query(name, workspace_id)
            alias_res = s.run(query, params)
            aliases = []
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    aliases.append(aname)
            result.append(
                {
                    "name": name,
                    "type": ent["type"],
                    "aliases": aliases,
                }
            )
        return result


@graph_retry()
def get_all_workspace_entities(workspace_id: str | None = None, limit: int = 100) -> list[dict]:
    """Get all entities in a workspace."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    with driver.session() as s:
        if workspace_id == DEFAULT_WORKSPACE_ID:
            res = s.run(
                "MATCH (e:Entity) "
                "WHERE e.workspace_id = $ws "
                "OR e.workspace_id IS NULL "
                "RETURN DISTINCT e "
                "LIMIT $lim",
                {"ws": workspace_id, "lim": limit},
            )
        else:
            res = s.run(
                "MATCH (e:Entity) WHERE e.workspace_id = $ws RETURN DISTINCT e LIMIT $lim",
                {"ws": workspace_id, "lim": limit},
            )
        return [{"name": r[0].get("name"), "type": r[0].get("type")} for r in res]


@graph_retry()
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
    # NOTE: `max_depth` is currently ignored — the implementation is fixed
    # 1-hop traversal. Kept in the signature for forward-compat.
    driver = get_graph_driver()
    results: list[dict] = []
    seen: set[tuple] = set()

    # Build optional temporal WHERE fragments with $param
    temporal = ""
    temporal_params: dict = {}
    if active_only:
        temporal += " AND r.valid_to IS NULL"
    if valid_after is not None:
        temporal += " AND (r.valid_from IS NULL OR r.valid_from >= $valid_after)"
        temporal_params["valid_after"] = valid_after
    if valid_before is not None:
        temporal += " AND (r.valid_from IS NULL OR r.valid_from <= $valid_before)"
        temporal_params["valid_before"] = valid_before

    with driver.session() as s:
        for name in entity_names:
            _all_rels = []
            base_params = {"name": name, **temporal_params}
            if workspace_id == DEFAULT_WORKSPACE_ID:
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)-[r]->(b:Entity) "
                        "WHERE e.name = $name"
                        f"{temporal} RETURN r",
                        base_params,
                    )
                )
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)<-[r]-(b:Entity) "
                        "WHERE e.name = $name"
                        f"{temporal} RETURN r",
                        base_params,
                    )
                )
            else:
                ws_params = {**base_params, "ws": workspace_id}
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)-[r]->(b:Entity) "
                        "WHERE e.name = $name "
                        "AND e.workspace_id = $ws "
                        "AND b.workspace_id = $ws"
                        f"{temporal} RETURN r",
                        ws_params,
                    )
                )
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)<-[r]-(b:Entity) "
                        "WHERE e.name = $name "
                        "AND e.workspace_id = $ws "
                        "AND b.workspace_id = $ws"
                        f"{temporal} RETURN r",
                        ws_params,
                    )
                )
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
                results.append(
                    {
                        "source": src_name,
                        "target": tgt_name,
                        "type": rel_type,
                        "valid_from": vf,
                        "valid_to": vt,
                    }
                )
            if len(results) >= 200:
                break
    return results[:200]


@graph_retry()
def get_relationships_at_date(
    entity_names: list[str], target_date: str, workspace_id: str | None = None, max_depth: int = 5
) -> list[dict]:
    """Get relationships valid at a specific date (ISO format YYYY-MM-DD).

    Temporal filtering is pushed into Cypher WHERE clauses so the DB
    can prune early instead of returning all edges for Python post-filter.

    Returns relationships where:
    - valid_from is NULL or <= target_date
    - valid_to is NULL or >= target_date
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    results: list[dict] = []
    seen: set[tuple] = set()
    temporal = (
        " AND (r.valid_from IS NULL OR r.valid_from <= $td)"
        " AND (r.valid_to IS NULL OR r.valid_to >= $td)"
    )
    with driver.session() as s:
        for name in entity_names:
            _all_rels = []
            base_params = {"name": name, "td": target_date}
            if workspace_id == DEFAULT_WORKSPACE_ID:
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)-[r]->(b:Entity) "
                        "WHERE e.name = $name"
                        f"{temporal} RETURN r",
                        base_params,
                    )
                )
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)<-[r]-(b:Entity) "
                        "WHERE e.name = $name"
                        f"{temporal} RETURN r",
                        base_params,
                    )
                )
            else:
                ws_params = {**base_params, "ws": workspace_id}
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)-[r]->(b:Entity) "
                        "WHERE e.name = $name "
                        "AND e.workspace_id = $ws "
                        "AND b.workspace_id = $ws"
                        f"{temporal} RETURN r",
                        ws_params,
                    )
                )
                _all_rels.extend(
                    s.run(
                        "MATCH (e:Entity)<-[r]-(b:Entity) "
                        "WHERE e.name = $name "
                        "AND e.workspace_id = $ws "
                        "AND b.workspace_id = $ws"
                        f"{temporal} RETURN r",
                        ws_params,
                    )
                )
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
                results.append(
                    {
                        "source": src_name,
                        "target": tgt_name,
                        "type": rel_type,
                        "valid_from": vf,
                        "valid_to": vt,
                    }
                )
            if len(results) >= 200:
                break
    return results[:200]


@graph_retry()
def get_doc_labels_by_entities(
    entity_names: list[str],
    workspace_id: str | None = None,
    user_groups: list[str] | None = None,
) -> list[dict]:
    """Get document labels for documents linked to given entities."""
    if not entity_names:
        return []
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    results: list[dict] = []
    seen_labels: set[str] = set()
    with driver.session() as s:
        for name in entity_names:
            # Path 1: via doc_labels property
            ent_res = s.run(
                "MATCH (e:Entity) WHERE e.name = $name AND e.workspace_id = $ws RETURN e",
                {"name": name, "ws": workspace_id},
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
            acl_frag, acl_params = _acl_clause(user_groups, "d")
            if workspace_id == DEFAULT_WORKSPACE_ID:
                d_filter = "(d.workspace_id = $ws OR d.workspace_id IS NULL)"
            else:
                d_filter = "d.workspace_id = $ws"
            doc_res = s.run(
                "MATCH (e:Entity)<-[:MENTIONS]-(d) "
                "WHERE e.name = $name "
                "AND e.workspace_id = $ws "
                "AND ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
                f"AND d.doc_label IS NOT NULL AND {d_filter} "
                f"{acl_frag} "
                "RETURN d",
                {"name": name, "ws": workspace_id, **acl_params},
            )
            for dr in doc_res:
                dnode = dr[0]
                dl = dnode.get("doc_label")
                if dl and dl not in seen_labels:
                    seen_labels.add(dl)

        # Fetch titles for all doc_labels
        acl_frag, acl_params = _acl_clause(user_groups, "d")
        for dl in seen_labels:
            d_res = s.run(
                "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
                "AND d.doc_label = $dl "
                f"{acl_frag} "
                "RETURN d",
                {"dl": dl, **acl_params},
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


@graph_retry()
def delete_document_node(doc_label: str, workspace_id: str | None = None) -> None:
    """Delete a document/issue node and its MENTIONS edges.

    Keeps entity nodes (they may be shared across documents).
    Used during incremental sync before re-ingesting an updated document.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    with driver.session() as s:
        s.run(
            "MATCH (d) WHERE ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
            "AND d.doc_label = $dl "
            "AND d.workspace_id = $ws "
            "DETACH DELETE d",
            {"dl": doc_label, "ws": workspace_id},
        )
    logger.info("graph.delete_document_node", doc_label=doc_label, workspace_id=workspace_id)


@graph_retry()
def get_related_documents(
    texts: list[str],
    workspace_id: str | None = None,
    user_groups: list[str] | None = None,
) -> list[dict]:
    """Get documents linked through shared entities."""
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()
    with driver.session() as s:
        # Step 1: get entities mentioned by matching documents
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d.raw_text IN $texts "
                "RETURN DISTINCT e",
                {"texts": texts},
            )
        else:
            ent_res = s.run(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE d.raw_text IN $texts "
                "AND d.workspace_id = $ws "
                "AND e.workspace_id = $ws "
                "RETURN DISTINCT e",
                {"texts": texts, "ws": workspace_id},
            )
        entity_names: set[str] = set()
        for r in ent_res:
            name = r[0].get("name")
            if name:
                entity_names.add(name)

        # Step 2: also collect alias names
        expanded_names = set(entity_names)
        for name in entity_names:
            query, params = _alias_query(name, workspace_id)
            alias_res = s.run(query, params)
            for ar in alias_res:
                aname = ar[0].get("name")
                if aname:
                    expanded_names.add(aname)

        # Step 3: find documents mentioning those entities
        acl_frag, acl_params = _acl_clause(user_groups, "m")
        results: list[dict] = []
        seen: set[str] = set()
        for ename in expanded_names:
            if workspace_id == DEFAULT_WORKSPACE_ID:
                doc_res = s.run(
                    "MATCH (ent:Entity)<-[:MENTIONS]-(m:Document) "
                    "WHERE ent.name = $ename "
                    f"{acl_frag} "
                    "RETURN m",
                    {"ename": ename, **acl_params},
                )
            else:
                doc_res = s.run(
                    "MATCH (ent:Entity)<-[:MENTIONS]-(m:Document) "
                    "WHERE ent.name = $ename "
                    "AND m.workspace_id = $ws "
                    f"{acl_frag} "
                    "RETURN m",
                    {"ename": ename, "ws": workspace_id, **acl_params},
                )
            for dr in doc_res:
                dnode = dr[0]
                doc_id = dnode.get("doc_id")
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    results.append(
                        {
                            "doc_id": doc_id,
                            "file_name": dnode.get("file_name"),
                        }
                    )
        return results


@graph_retry()
def get_graph_overview(
    workspace_id: str | None = None, limit: int = 100, user_groups: list[str] | None = None
) -> dict:
    """Get top-N most connected entities with edges between them.

    Returns nodes sorted by connection count (degree) and all edges
    that exist between the returned nodes.

    Note: user_groups is accepted for API consistency but not used here.
    This function queries Entity→Entity edges only (no Document nodes).
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    limit = max(1, min(limit, 500))
    driver = get_graph_driver()
    with driver.session() as s:
        params: dict = {"ws": workspace_id}
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter = "(a.workspace_id = $ws OR a.workspace_id IS NULL)"
        else:
            ws_filter = "a.workspace_id = $ws"

        q_edges = f"MATCH (a:Entity)-[r]->(b:Entity) WHERE {ws_filter} RETURN a, r, b"
        logger.debug("graph_overview.edges", query=q_edges)
        all_edges: list[dict] = []
        node_map: dict[int, dict] = {}
        try:
            for rec in s.run(q_edges, params):
                src_node = rec[0]
                rel = rec[1]
                tgt_node = rec[2]
                src_id = src_node.id
                tgt_id = tgt_node.id
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
                all_edges.append(
                    {
                        "source": src_id,
                        "target": tgt_id,
                        "type": rel.get("type"),
                        "valid_from": rel.get("valid_from"),
                        "valid_to": rel.get("valid_to"),
                    }
                )
        except Exception as exc:
            logger.warning("graph_overview.edges_failed", error=str(exc))

        # Also fetch isolated nodes (no edges)
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter_e = "(e.workspace_id = $ws OR e.workspace_id IS NULL)"
        else:
            ws_filter_e = "e.workspace_id = $ws"
        q_nodes = f"MATCH (e:Entity) WHERE {ws_filter_e} RETURN e"
        logger.debug("graph_overview.nodes", query=q_nodes)
        for rec in s.run(q_nodes, params):
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
        "nodes": nodes,
        "edges": edges,
        "truncated": len(nodes) >= limit,
    }


@graph_retry()
def get_graph_expand(
    entity_id: int,
    workspace_id: str | None = None,
    depth: int = 2,
    limit: int = 50,
    user_groups: list[str] | None = None,
) -> dict:
    """Expand a single entity by Neo4j internal ID.

    Uses the same single-query approach as get_graph_overview:
    fetch ALL workspace edges once, then find neighbors of entity_id
    by walking edges in Python up to *depth* hops.

    Note: user_groups is accepted for API consistency but not used here.
    This function queries Entity→Entity edges only (no Document nodes).
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    depth = max(1, min(depth, 3))
    limit = max(1, min(limit, 500))
    driver = get_graph_driver()
    with driver.session() as s:
        params: dict = {"ws": workspace_id}
        if workspace_id == DEFAULT_WORKSPACE_ID:
            ws_filter = "(a.workspace_id = $ws OR a.workspace_id IS NULL)"
        else:
            ws_filter = "a.workspace_id = $ws"
        q_edges = f"MATCH (a:Entity)-[r]->(b:Entity) WHERE {ws_filter} RETURN a, r, b"
        logger.debug("graph_expand.edges", query=q_edges)

        all_edges: list[dict] = []
        node_map: dict[int, dict] = {}
        adj: dict[int, set[int]] = {}
        try:
            for rec in s.run(q_edges, params):
                src_node = rec[0]
                rel = rec[1]
                tgt_node = rec[2]
                src_id = src_node.id
                tgt_id = tgt_node.id
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
                adj.setdefault(src_id, set()).add(tgt_id)
                adj.setdefault(tgt_id, set()).add(src_id)
                all_edges.append(
                    {
                        "source": src_id,
                        "target": tgt_id,
                        "type": rel.get("type"),
                        "valid_from": rel.get("valid_from"),
                        "valid_to": rel.get("valid_to"),
                    }
                )
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
        "nodes": nodes,
        "edges": edges,
        "truncated": len(nodes) >= limit,
    }
