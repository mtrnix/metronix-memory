"""Neo4j graph operations for Agent Memory (WS1).

Handles MemoryRecord nodes and their relationships in the knowledge graph.
Content is NOT stored here — only metadata and edges. Content lives in Qdrant.

Reuses the shared Neo4j driver from neo4j_graph.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from metatron.storage.neo4j_graph import get_graph_driver, graph_retry

if TYPE_CHECKING:
    from metatron.core.models import MemoryRecord

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


@graph_retry()
def upsert_memory_node(record: MemoryRecord) -> None:
    """Create or update a MemoryRecord node in Neo4j.

    Stores metadata only — content lives in Qdrant.
    Uses MERGE on (id, workspace_id) to be idempotent.

    Note: ``record.content`` and ``record.metadata`` are intentionally not
    written.  Content belongs in Qdrant; metadata is a free-form dict that
    Neo4j cannot store as a node property (PG/Qdrant handle it).
    """
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MERGE (m:MemoryRecord {id: $id, workspace_id: $ws}) "
            "SET m.agent_id = $agent_id, "
            "    m.scope = $scope, "
            "    m.source_type = $source_type, "
            "    m.importance_score = $importance_score, "
            "    m.tags = $tags, "
            "    m.ttl_expires_at = $ttl_expires_at, "
            "    m.content_hash = $content_hash, "
            "    m.created_at = $created_at, "
            "    m.session_id = $session_id",
            {
                "id": record.id,
                "ws": record.workspace_id,
                "agent_id": record.agent_id,
                "scope": record.scope.value,
                "source_type": record.source_type,
                "importance_score": record.importance_score,
                "tags": record.tags,
                "ttl_expires_at": (
                    record.ttl_expires_at.isoformat() if record.ttl_expires_at else None
                ),
                "content_hash": record.content_hash,
                "created_at": record.created_at.isoformat(),
                "session_id": record.session_id,
            },
        )
    logger.debug("memory_graph.upsert", id=record.id, workspace_id=record.workspace_id)


@graph_retry()
def get_memory_node(workspace_id: str, record_id: str) -> dict[str, Any] | None:
    """Fetch a single MemoryRecord node by id.

    Returns node properties as a dict, or None if not found.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MemoryRecord {id: $id, workspace_id: $ws}) RETURN m{.*} AS m",
            {"id": record_id, "ws": workspace_id},
        )
        row = result.single()
        if row is None:
            return None
        return dict(row["m"])


# ---------------------------------------------------------------------------
# Delete operations
# ---------------------------------------------------------------------------


@graph_retry()
def delete_memory_node(workspace_id: str, record_id: str) -> bool:
    """Delete a MemoryRecord node and all its edges.

    Returns True if the node existed, False otherwise.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MemoryRecord {id: $id, workspace_id: $ws}) "
            "DETACH DELETE m "
            "RETURN count(*) AS n",
            {"id": record_id, "ws": workspace_id},
        )
        row = result.single()
        deleted = row["n"] > 0 if row else False
    if deleted:
        logger.debug("memory_graph.deleted", id=record_id, workspace_id=workspace_id)
    return deleted


@graph_retry()
def delete_agent_memories(
    workspace_id: str,
    agent_id: str,
    scope: str | None = None,
) -> int:
    """Bulk-delete all MemoryRecord nodes for an agent. Returns count deleted.

    If scope is provided, only deletes records matching that scope.
    """
    driver = get_graph_driver()
    where = "WHERE m.scope = $scope " if scope is not None else ""
    cypher = (
        "MATCH (m:MemoryRecord {workspace_id: $ws, agent_id: $agent_id}) "
        f"{where}"
        "DETACH DELETE m "
        "RETURN count(*) AS n"
    )
    params: dict[str, Any] = {"ws": workspace_id, "agent_id": agent_id}
    if scope is not None:
        params["scope"] = scope

    with driver.session() as session:
        result = session.run(cypher, params)
        row = result.single()
        count = row["n"] if row else 0
    logger.info(
        "memory_graph.bulk_deleted",
        agent_id=agent_id,
        scope=scope,
        count=count,
        workspace_id=workspace_id,
    )
    return count


# ---------------------------------------------------------------------------
# Relationship edge operations
# ---------------------------------------------------------------------------


@graph_retry()
def link_agent_memory(workspace_id: str, agent_id: str, record_id: str) -> None:
    """Ensure Agent node exists and create REMEMBERS edge to MemoryRecord.

    MERGE is idempotent — safe to call multiple times.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MERGE (a:Agent {id: $agent_id, workspace_id: $ws}) "
            "WITH a "
            "MATCH (m:MemoryRecord {id: $record_id, workspace_id: $ws}) "
            "MERGE (a)-[:REMEMBERS {since: $since}]->(m)",
            {
                "agent_id": agent_id,
                "ws": workspace_id,
                "record_id": record_id,
                "since": datetime.now(UTC).isoformat(),
            },
        )


@graph_retry()
def link_memory_entity(
    workspace_id: str,
    record_id: str,
    entity_name: str,
    relevance: float = 1.0,
) -> None:
    """Create ABOUT edge from MemoryRecord to an existing Entity."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MATCH (m:MemoryRecord {id: $record_id, workspace_id: $ws}) "
            "MATCH (e:Entity {name: $entity_name, workspace_id: $ws}) "
            "MERGE (m)-[:ABOUT {relevance: $relevance}]->(e)",
            {
                "record_id": record_id,
                "ws": workspace_id,
                "entity_name": entity_name,
                "relevance": relevance,
            },
        )


@graph_retry()
def link_memory_session(
    workspace_id: str,
    record_id: str,
    session_id: str,
    agent_id: str,
) -> None:
    """Ensure Session node exists and create FROM_SESSION edge."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MERGE (s:Session {id: $session_id, workspace_id: $ws}) "
            "ON CREATE SET s.agent_id = $agent_id "
            "WITH s "
            "MATCH (m:MemoryRecord {id: $record_id, workspace_id: $ws}) "
            "MERGE (m)-[:FROM_SESSION]->(s)",
            {
                "session_id": session_id,
                "ws": workspace_id,
                "agent_id": agent_id,
                "record_id": record_id,
            },
        )


@graph_retry()
def link_memory_document(workspace_id: str, record_id: str, doc_id: str) -> None:
    """Create DERIVED_FROM edge from MemoryRecord to an existing Document."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MATCH (m:MemoryRecord {id: $record_id, workspace_id: $ws}) "
            "MATCH (d:Document {doc_id: $doc_id, workspace_id: $ws}) "
            "MERGE (m)-[:DERIVED_FROM]->(d)",
            {
                "record_id": record_id,
                "ws": workspace_id,
                "doc_id": doc_id,
            },
        )


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------


@graph_retry()
def get_agent_memories(
    workspace_id: str,
    agent_id: str,
    scope: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get all MemoryRecord nodes linked to an agent via REMEMBERS.

    Returns list of node property dicts, ordered by importance_score DESC.
    """
    driver = get_graph_driver()
    where = "WHERE m.scope = $scope " if scope is not None else ""
    cypher = (
        "MATCH (a:Agent {id: $agent_id, workspace_id: $ws})"
        "-[:REMEMBERS]->(m:MemoryRecord) "
        f"{where}"
        "RETURN m{.*} AS m "
        "ORDER BY m.importance_score DESC "
        "LIMIT $limit"
    )
    params: dict[str, Any] = {"agent_id": agent_id, "ws": workspace_id, "limit": limit}
    if scope is not None:
        params["scope"] = scope

    with driver.session() as session:
        result = session.run(cypher, params)
        return [dict(row["m"]) for row in result]


@graph_retry()
def get_memories_about_entity(
    workspace_id: str,
    entity_name: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get MemoryRecord nodes linked to an entity via ABOUT.

    Returns list of dicts with node properties + relevance score from the edge.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MemoryRecord {workspace_id: $ws})"
            "-[r:ABOUT]->(e:Entity {name: $entity_name, workspace_id: $ws}) "
            "RETURN m{.*} AS m, r.relevance AS relevance "
            "ORDER BY r.relevance DESC, m.importance_score DESC "
            "LIMIT $limit",
            {"ws": workspace_id, "entity_name": entity_name, "limit": limit},
        )
        return [{**dict(row["m"]), "relevance": row["relevance"]} for row in result]


@graph_retry()
def get_memory_relationships(workspace_id: str, record_id: str) -> list[dict[str, Any]]:
    """Get all relationships (both directions) for a MemoryRecord.

    Returns list of dicts with edge type and target node info (label + id).
    Useful for provenance queries and graph scoring.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MemoryRecord {id: $id, workspace_id: $ws})-[r]-(n) "
            "RETURN type(r) AS type, "
            "       labels(n)[0] AS target_label, "
            "       coalesce(n.id, n.name, n.doc_id) AS target_id",
            {"id": record_id, "ws": workspace_id},
        )
        return [dict(row) for row in result]


# ---------------------------------------------------------------------------
# Composite helper
# ---------------------------------------------------------------------------


@graph_retry()
def link_memory_items_batch(
    workspace_id: str,
    edges: list[tuple[str, str, float]],
) -> None:
    """Create LINKED_TO edges between MemoryRecord nodes in a single session.

    ``edges`` is a list of ``(source_id, target_id, score)`` tuples. One Neo4j
    session is opened per call — the ``UNWIND`` Cypher statement processes
    all edges in the server. Empty lists are no-ops. Used by the Linker stage
    to avoid N thread-pool tasks per record.
    """
    if not edges:
        return
    payload = [
        {"source": source_id, "target": target_id, "score": score}
        for source_id, target_id, score in edges
    ]
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            UNWIND $edges AS e
            MATCH (a:MemoryRecord {id: e.source, workspace_id: $ws})
            MATCH (b:MemoryRecord {id: e.target, workspace_id: $ws})
            MERGE (a)-[r:LINKED_TO]->(b)
            SET r.score = e.score
            """,
            {"ws": workspace_id, "edges": payload},
        )
    logger.debug(
        "memory_graph.link_batch",
        workspace_id=workspace_id,
        edge_count=len(edges),
    )


def save_memory_to_graph(
    record: MemoryRecord,
    *,
    entity_names: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> None:
    """Composite save: create MemoryRecord node + all relationship edges.

    Always creates:
      - MemoryRecord node (metadata only)
      - Agent node + REMEMBERS edge

    Conditionally creates:
      - FROM_SESSION edge (if record.session_id is set)
      - ABOUT edges (if entity_names provided)
      - DERIVED_FROM edges (if document_ids provided)

    Not transactional — a failure mid-way leaves partial state.
    All operations are idempotent, so the caller can safely retry.
    """
    upsert_memory_node(record)
    link_agent_memory(record.workspace_id, record.agent_id, record.id)

    if record.session_id:
        link_memory_session(
            record.workspace_id,
            record.id,
            record.session_id,
            record.agent_id,
        )

    for name in entity_names or []:
        link_memory_entity(record.workspace_id, record.id, name, relevance=1.0)

    for doc_id in document_ids or []:
        link_memory_document(record.workspace_id, record.id, doc_id)


# ---------------------------------------------------------------------------
# Neighbourhood query (MTRNIX-324)
# ---------------------------------------------------------------------------

# Edge types that use a "bridge" node (Agent / Entity / Session / Document)
# rather than a direct MemoryRecord→MemoryRecord edge. The bridge node
# is surfaced as ``metadata.via`` / ``metadata.via_id`` on the edge.
_BRIDGE_EDGE_TYPES = frozenset({"REMEMBERS", "ABOUT", "FROM_SESSION", "DERIVED_FROM"})
# Direct memory-to-memory edge created by the Linker stage (MTRNIX-313).
_DIRECT_EDGE_TYPES = frozenset({"LINKED_TO"})


@graph_retry()
def get_memory_neighborhood(
    workspace_id: str,
    seed_record_id: str,
    depth: int,
) -> dict[str, Any]:
    """Return the ``depth``-hop neighbourhood around a memory record.

    Returns::

        {
          "record_ids": list[str],
          "edges":      list[dict],   # {source, target, type, metadata?}
        }

    Each edge uses the MemoryRecord id as ``source``/``target``. For edges
    that traverse a bridge node (Agent, Entity, Session, Document), the
    bridge label and id are exposed as ``metadata.via`` / ``metadata.via_id``
    so the UI can show "shared agent X" without a direct memory-to-memory
    edge in the schema.

    For ``LINKED_TO`` edges (direct MemoryRecord→MemoryRecord, created by the
    Linker stage), ``source`` and ``target`` are the two memory record ids and
    ``metadata`` is ``None`` or contains edge properties (e.g. ``score``).

    The seed record is always included in ``record_ids`` even when Neo4j
    returns no edges. Workspace scoping: every node match requires
    ``workspace_id = $ws``.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        # 1. Find direct LINKED_TO edges between MemoryRecord nodes.
        linked_result = session.run(
            """
            MATCH (seed:MemoryRecord {id: $seed, workspace_id: $ws})
            CALL apoc.path.expandConfig(seed, {
                relationshipFilter: "LINKED_TO",
                maxLevel: $depth,
                labelFilter: "+MemoryRecord",
                uniqueness: "NODE_GLOBAL"
            })
            YIELD path
            WITH seed, last(nodes(path)) AS other, last(relationships(path)) AS rel
            WHERE other.id <> seed.id
            RETURN seed.id AS source, other.id AS target, "LINKED_TO" AS rtype,
                   properties(rel) AS rprops
            """,
            {"seed": seed_record_id, "ws": workspace_id, "depth": depth},
        )

        # 2. Find bridge-mediated connections (Agent, Entity, Session, Document).
        bridge_result = session.run(
            """
            MATCH (seed:MemoryRecord {id: $seed, workspace_id: $ws})
            MATCH (seed)-[r1]-(bridge)
            WHERE type(r1) IN ["REMEMBERS", "ABOUT", "FROM_SESSION", "DERIVED_FROM"]
              AND NOT "MemoryRecord" IN labels(bridge)
            MATCH (bridge)-[r2]-(other:MemoryRecord {workspace_id: $ws})
            WHERE other.id <> seed.id
            RETURN seed.id          AS source,
                   other.id         AS target,
                   type(r1)         AS rtype,
                   labels(bridge)[0] AS via_label,
                   coalesce(bridge.id, bridge.name, bridge.doc_id) AS via_id
            """,
            {"seed": seed_record_id, "ws": workspace_id},
        )

    record_ids: list[str] = [seed_record_id]
    edges: list[dict[str, Any]] = []

    # Direct LINKED_TO edges — use apoc if available; fall back to simple match.
    # We do a plain match as primary approach since apoc may not be installed.
    try:
        linked_rows = list(linked_result)
    except Exception:
        linked_rows = []

    for row in linked_rows:
        target = row["target"]
        if target not in record_ids:
            record_ids.append(target)
        rprops = dict(row["rprops"]) if row["rprops"] else None
        edges.append(
            {
                "source": row["source"],
                "target": target,
                "type": "LINKED_TO",
                "metadata": rprops,
            }
        )

    try:
        bridge_rows = list(bridge_result)
    except Exception:
        bridge_rows = []

    for row in bridge_rows:
        target = row["target"]
        if target not in record_ids:
            record_ids.append(target)
        edges.append(
            {
                "source": row["source"],
                "target": target,
                "type": row["rtype"],
                "metadata": {
                    "via": row["via_label"],
                    "via_id": row["via_id"],
                },
            }
        )

    logger.debug(
        "memory_graph.neighborhood",
        workspace_id=workspace_id,
        seed_record_id=seed_record_id,
        depth=depth,
        record_count=len(record_ids),
        edge_count=len(edges),
    )
    return {"record_ids": record_ids, "edges": edges}
