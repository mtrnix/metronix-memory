"""Neo4j graph database connection management + core graph write operations.

Uses the neo4j Python driver over bolt:// protocol.
Originally Memgraph-backed; migrated to Neo4j CE for disk-based scaling.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import re
import time
from datetime import UTC, datetime
from functools import wraps
from threading import Lock

import structlog
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metronix.llm import chat_completion

logger = structlog.get_logger()

DEFAULT_WORKSPACE_ID = "MTRNIX"


class GraphExtractionError(Exception):
    """LLM-based graph extraction (NER) gave up after exhausting its retries.

    Distinct from Neo4j/connection errors: this signals the *document* could not
    be extracted (e.g. the LLM timed out repeatedly), so callers should park it
    as ``graph_failed`` rather than retry it forever.
    """


_driver = None
_driver_lock = Lock()


def _normalize_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def get_graph_driver(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
):
    """Get shared Neo4j driver instance (singleton).

    Parameters default to values from Settings (env vars) when not provided.
    Verifies connectivity on cached driver; recreates if stale.
    """
    global _driver
    with _driver_lock:
        if _driver is not None:
            try:
                _driver.verify_connectivity()
            except AttributeError:
                pass  # older driver version without verify_connectivity
            except Exception as e:
                logger.warning("neo4j.driver.stale", error=str(e))
                with contextlib.suppress(Exception):
                    _driver.close()
                _driver = None

        if _driver is None:
            if uri is None or user is None or password is None:
                from metronix.core.config import get_settings

                s = get_settings()
                uri = uri or s.neo4j_uri
                user = user if user is not None else s.neo4j_user
                password = password if password is not None else s.neo4j_password
            auth = (user, password) if user else None
            _driver = GraphDatabase.driver(
                uri,
                auth=auth,
                max_connection_pool_size=50,
                connection_acquisition_timeout=30,
            )
            logger.info("neo4j.driver.initialized", uri=uri)
    return _driver


def close_graph_driver() -> None:
    """Close the shared Neo4j driver (call on shutdown)."""
    global _driver
    if _driver is not None:
        with _driver_lock:
            if _driver is not None:
                _driver.close()
                _driver = None
                logger.info("neo4j.driver.closed")


atexit.register(close_graph_driver)


def graph_retry(max_attempts: int = 3):
    """Retry decorator for graph operations on stale connections.

    On connection error: resets the driver singleton so the next call
    creates a fresh connection.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except (
                    ServiceUnavailable,
                    SessionExpired,
                    BrokenPipeError,
                    ConnectionError,
                ) as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "neo4j.retry",
                            func=func.__name__,
                            attempt=attempt + 1,
                            error=str(e),
                        )
                        close_graph_driver()
                except Exception as e:
                    if "broken pipe" in str(e).lower() or "connection" in str(e).lower():
                        last_error = e
                        if attempt < max_attempts - 1:
                            logger.warning(
                                "neo4j.retry",
                                func=func.__name__,
                                attempt=attempt + 1,
                                error=str(e),
                            )
                            close_graph_driver()
                            continue
                    raise
            if last_error:
                raise last_error
            raise RuntimeError(
                f"graph_retry: max_attempts={max_attempts} did not allow any attempts"
            )

        return wrapper

    return decorator


def extract_graph_from_text(text: str, max_text_length: int = 8000) -> dict:
    """Extract entities and relationships from text via LLM."""
    text_truncated = len(text) > max_text_length
    if text_truncated:
        text = text[:max_text_length] + "..."
        logger.warning("graph.extract.truncated", max_len=max_text_length)

    prompt = (
        "Extract entities and relationships from the text. Return ONLY JSON:\n\n"
        '{"entities": [{"name": "...", "type": "..."}], '
        '"relationships": [{"source": "...", "target": "...", "type": "..."}]}\n\n'
        "ENTITY TYPE RULES — you MUST use ONLY these types:\n"
        "Person, Organization, Project, Task, Technology, Document, "
        "Concept, Service, Event, Location.\n"
        "Do NOT invent new types. Map everything to the closest type.\n"
        "Examples: frameworks/libraries/databases → Technology, "
        "epics/initiatives → Project, bugs/stories/tickets → Task, "
        "teams/departments → Organization, APIs/platforms → Service.\n\n"
        "ENTITY NAME RULES:\n"
        "- Use proper names, not descriptions (e.g. 'Qdrant' not "
        "'vector database for storing embeddings')\n"
        "- Do NOT include URLs, file paths, or code identifiers\n"
        "- Keep names under 50 characters\n\n"
        f'Text:\n\n"""{text}"""'
    )

    # Push NER-specific metadata onto the telemetry context so emit_log can
    # include it in the ner_extraction row's metadata field. add_extra_metadata
    # merges instead of overwriting, so adjacent callers in the same scope keep
    # their keys (e.g. ingestion-level doc_label).
    try:
        from metronix.llm.telemetry import add_extra_metadata

        add_extra_metadata(text_truncated=text_truncated)
    except Exception:
        pass  # telemetry is best-effort; never block the NER path

    from metronix.core.config import get_settings

    ner_timeout = get_settings().graph_extraction_llm_timeout

    content = ""
    for attempt in range(3):
        try:
            content = chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "You extract knowledge graphs from text. "
                        "Return only valid JSON. Use only these entity types: "
                        "Person, Organization, Project, Task, Technology, "
                        "Document, Concept, Service, Event, Location.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                json_mode=True,
                timeout=ner_timeout,
                call_site="ner_extraction",
            )
            break
        except Exception as e:
            if attempt < 2:
                wait = 2 * (attempt + 1)
                logger.warning(
                    "graph.extract.retry",
                    attempt=attempt + 1,
                    wait=wait,
                    error=str(e),
                )
                time.sleep(wait)
            else:
                # Hard LLM failure (timeout / connection / 5xx) after all retries.
                # Raise a typed error instead of returning empty entities: callers
                # park the document as graph_failed (terminal) rather than marking
                # it graph_synced with an empty graph or retrying it forever.
                logger.error("graph.extract.failed", error=str(e))
                raise GraphExtractionError(str(e)) from e

    content = content.strip()
    if "<think>" in content:
        parts = content.split("</think>")
        if len(parts) > 1:
            content = parts[-1].strip()
    if "```" in content:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if m:
            content = m.group(1).strip()
    if not content.startswith("{"):
        s, e = content.find("{"), content.rfind("}")
        if s != -1 and e != -1 and e > s:
            content = content[s : e + 1]
    if not content:
        return {"entities": [], "relationships": []}

    try:
        data = json.loads(content)
        raw_entities = data.get("entities", [])
        raw_relationships = data.get("relationships", [])

        from metronix.storage.graph_entities import (
            is_role_not_person,
            is_valid_entity_name,
            normalize_entity_type,
            normalize_person_name,
        )

        entities: list[dict] = []
        merged_aliases: dict[str, str] = {}
        for ent in raw_entities:
            name = (ent.get("name") or "").strip()
            if not is_valid_entity_name(name):
                logger.debug("graph.extract.entity_filtered", name=name)
                continue
            ent_type = normalize_entity_type(ent.get("type", ""))

            if is_role_not_person(name, ent_type):
                logger.debug(
                    "graph.extract.role_reclassified",
                    name=name,
                    old_type=ent_type,
                )
                ent_type = "Organization"

            if ent_type == "Person":
                canonical = normalize_person_name(name, ent_type)
                if canonical != name:
                    merged_aliases[name] = canonical
                    logger.debug(
                        "graph.extract.person_merged",
                        original=name,
                        canonical=canonical,
                    )
                    name = canonical

            ent["name"] = name
            ent["type"] = ent_type
            entities.append(ent)

        mention_counts: dict[str, int] = {}
        for ent in entities:
            name = ent["name"]
            mention_counts[name] = mention_counts.get(name, 0) + 1

        seen_names: set[str] = set()
        deduped: list[dict] = []
        for ent in entities:
            if ent["name"] not in seen_names:
                seen_names.add(ent["name"])
                deduped.append(ent)
        entities = deduped

        valid_names = {e["name"] for e in entities}
        relationships: list[dict] = []
        for rel in raw_relationships:
            src = (rel.get("source") or "").strip()
            tgt = (rel.get("target") or "").strip()
            src = merged_aliases.get(src, src)
            tgt = merged_aliases.get(tgt, tgt)
            if src in valid_names and tgt in valid_names:
                rel["source"] = src
                rel["target"] = tgt
                relationships.append(rel)

        logger.info(
            "graph.extract.ok",
            entities=len(entities),
            rels=len(relationships),
            filtered=len(raw_entities) - len(entities),
            merged=len(merged_aliases),
        )
        return {
            "entities": entities,
            "relationships": relationships,
            "merged_aliases": merged_aliases,
            "mention_counts": mention_counts,
        }
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("graph.extract.parse_error", error=str(exc))
        return {"entities": [], "relationships": [], "mention_counts": {}}


@graph_retry()
def write_doc_graph(
    text: str,
    file_name: str,
    user_id: str = "user",
    workspace_id: str | None = None,
    doc_label: str | None = None,
    upload_time: str | None = None,
    doc_date: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Extract graph from text and write document + entities to Neo4j."""
    workspace_id = _normalize_workspace_id(workspace_id)
    if doc_label is None:
        upload_time = upload_time or datetime.now(UTC).isoformat()
        doc_label = f"{workspace_id}:{user_id}:{file_name}:{upload_time}"
    elif upload_time is None:
        upload_time = datetime.now(UTC).isoformat()

    graph = extract_graph_from_text(text)
    entities = graph["entities"]
    relationships = graph["relationships"]
    mention_counts: dict[str, int] = graph.get("mention_counts", {})
    merged_aliases: dict[str, str] = graph.get("merged_aliases", {})
    doc_id = doc_label
    edge_date = doc_date or upload_time
    logger.info("graph.write_doc", entities=len(entities), rels=len(relationships))

    access_groups = metadata.get("access_groups") if metadata else None
    driver = get_graph_driver()

    with driver.session() as session:
        session.run(
            "MERGE (u:User {user_id: $uid, workspace_id: $ws}) "
            "MERGE (d:Document {doc_id: $did}) "
            "SET d.file_name = $fn, d.upload_time = $ut, d.raw_text = $txt, "
            "    d.doc_label = $dl, d.workspace_id = $ws, d.user_id = $uid, "
            "    d.access_groups = $ag "
            "MERGE (u)-[r:UPLOADED]->(d) "
            "SET r.valid_from = $ut",
            {
                "uid": user_id,
                "ws": workspace_id,
                "did": doc_id,
                "fn": file_name,
                "ut": upload_time,
                "txt": text,
                "dl": doc_label,
                "ag": access_groups,
            },
        )
        for ent in entities:
            name = ent.get("name")
            if not name:
                continue
            session.run(
                "MATCH (d:Document {doc_id: $did}) "
                "MERGE (e:Entity {name: $name, workspace_id: $ws}) "
                "SET e.type = $etype, e.user_id = $uid, "
                "    e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [$dl] "
                "    WHEN $dl IN e.doc_labels THEN e.doc_labels "
                "    ELSE e.doc_labels + [$dl] END "
                "MERGE (d)-[r:MENTIONS]->(e) "
                "SET r.valid_from = $edate, r.mention_count = $mention_count",
                {
                    "did": doc_id,
                    "name": name,
                    "ws": workspace_id,
                    "etype": ent.get("type", "unknown"),
                    "uid": user_id,
                    "dl": doc_label,
                    "edate": edge_date,
                    "mention_count": mention_counts.get(name, 1),
                },
            )
        for rel in relationships:
            session.run(
                "MERGE (e1:Entity {name: $src, workspace_id: $ws}) "
                "MERGE (e2:Entity {name: $tgt, workspace_id: $ws}) "
                "SET e1.doc_labels = CASE WHEN e1.doc_labels IS NULL THEN [$dl] "
                "    WHEN $dl IN e1.doc_labels THEN e1.doc_labels "
                "    ELSE e1.doc_labels + [$dl] END, "
                "    e2.doc_labels = CASE WHEN e2.doc_labels IS NULL THEN [$dl] "
                "    WHEN $dl IN e2.doc_labels THEN e2.doc_labels "
                "    ELSE e2.doc_labels + [$dl] END "
                "MERGE (e1)-[r:RELATION {type: $rtype, workspace_id: $ws}]->(e2) "
                "SET r.valid_from = $edate",
                {
                    "src": rel.get("source"),
                    "tgt": rel.get("target"),
                    "ws": workspace_id,
                    "dl": doc_label,
                    "rtype": rel.get("type"),
                    "edate": edge_date,
                },
            )
        for alias_name, canonical_name in merged_aliases.items():
            if alias_name.lower().strip() == canonical_name.lower().strip():
                continue
            session.run(
                "MERGE (a:Entity {name: $alias, workspace_id: $ws}) "
                "SET a.type = 'Person' "
                "MERGE (c:Entity {name: $canon, workspace_id: $ws}) "
                "MERGE (a)-[:ALIAS]->(c)",
                {"alias": alias_name, "canon": canonical_name, "ws": workspace_id},
            )
    logger.info("graph.write_doc.done", file_name=file_name, workspace_id=workspace_id)


@graph_retry()
def write_chunk_hierarchy(
    workspace_id: str,
    root_chunk_id: str,
    child_chunk_ids: list[str],
    doc_label: str,
) -> None:
    """Create Chunk nodes and CHILD_OF edges for root-child hierarchy.

    Creates a root Chunk node and child Chunk nodes, then links each
    child to the root via a CHILD_OF relationship.  All nodes are
    scoped to the workspace for isolation.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    driver = get_graph_driver()

    with driver.session() as session:
        session.run(
            "MERGE (r:Chunk {chunk_id: $root, workspace_id: $ws}) "
            "SET r.chunk_type = 'root', r.doc_label = $dl",
            {"root": root_chunk_id, "ws": workspace_id, "dl": doc_label},
        )
        for child_id in child_chunk_ids:
            session.run(
                "MERGE (c:Chunk {chunk_id: $cid, workspace_id: $ws}) "
                "SET c.chunk_type = 'child', c.doc_label = $dl "
                "WITH c "
                "MATCH (r:Chunk {chunk_id: $root, workspace_id: $ws}) "
                "MERGE (c)-[:CHILD_OF]->(r)",
                {"cid": child_id, "ws": workspace_id, "dl": doc_label, "root": root_chunk_id},
            )

    logger.info(
        "graph.chunk_hierarchy.done",
        root=root_chunk_id,
        children=len(child_chunk_ids),
        workspace_id=workspace_id,
    )


@graph_retry()
def ensure_graph_indexes() -> None:
    """Create node property indexes for frequently queried fields.

    Uses Neo4j CREATE INDEX IF NOT EXISTS syntax.
    """
    driver = get_graph_driver()
    with driver.session() as session:
        for stmt in [
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.workspace_id)",
            "CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.doc_label)",
            "CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.workspace_id)",
            "CREATE INDEX IF NOT EXISTS FOR (j:JiraIssue) ON (j.issue_key)",
            "CREATE INDEX IF NOT EXISTS FOR (j:JiraIssue) ON (j.workspace_id)",
            # Agent Memory schema indexes
            "CREATE INDEX IF NOT EXISTS FOR (a:Agent) ON (a.workspace_id)",
            "CREATE INDEX IF NOT EXISTS FOR (m:MemoryRecord) ON (m.workspace_id, m.scope)",
            "CREATE INDEX IF NOT EXISTS FOR (m:MemoryRecord) ON (m.ttl_expires_at)",
        ]:
            try:  # noqa: SIM105
                session.run(stmt)
            except Exception:
                pass  # Index may already exist
    logger.info("neo4j.indexes.ensured")


@graph_retry()
def delete_workspace_graph(workspace_id: str) -> None:
    """Delete all graph data for a specific workspace. WARNING: permanent."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.workspace_id = $ws DETACH DELETE n",
            {"ws": workspace_id},
        )
    logger.info("graph.workspace.deleted", workspace_id=workspace_id)
