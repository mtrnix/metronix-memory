"""Memgraph connection management + core graph write operations.

Migrated from PoC: db/memgraph.py (driver) + indexers/memgraph_workspace.py (write ops)
"""
# TODO: async migration
from __future__ import annotations

import atexit
import json
import re
import time
from datetime import UTC, datetime
from functools import wraps
from threading import Lock

import structlog
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metatron.llm import chat_completion  # wired up when metatron.llm.chat_completion is available

logger = structlog.get_logger()

DEFAULT_WORKSPACE_ID = "MTRNIX"


def _esc(value) -> str:
    """Escape a value for safe inline use in Cypher queries.

    Memgraph 2.18.1 does not support $param named parameters via the
    neo4j Python driver, so all values must be inlined.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def _esc_list(values) -> str:
    """Escape a list for inline use in Cypher."""
    return "[" + ", ".join(_esc(v) for v in values) + "]"

_driver = None
_driver_lock = Lock()


def _normalize_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def get_memgraph_driver(uri: str | None = None,
                        user: str | None = None,
                        password: str | None = None):
    """Get shared Memgraph/Neo4j driver instance (singleton).

    Parameters default to values from Settings (env vars) when not provided.

    Verifies connectivity on cached driver; recreates if stale (e.g. after long LLM calls).
    """
    global _driver
    with _driver_lock:
        if _driver is not None:
            try:
                _driver.verify_connectivity()
            except AttributeError:
                pass  # older driver version without verify_connectivity
            except Exception as e:
                logger.warning("memgraph.driver.stale", error=str(e))
                try:
                    _driver.close()
                except Exception:
                    pass
                _driver = None

        if _driver is None:
            if uri is None or user is None or password is None:
                from metatron.core.config import get_settings
                s = get_settings()
                uri = uri or s.memgraph_uri
                user = user if user is not None else s.memgraph_user
                password = password if password is not None else s.memgraph_password
            auth = (user, password) if user else None
            _driver = GraphDatabase.driver(
                uri, auth=auth,
                max_connection_pool_size=50,
                connection_acquisition_timeout=30,
            )
            logger.info("memgraph.driver.initialized", uri=uri)
    return _driver


def close_memgraph_driver() -> None:
    """Close the shared Memgraph driver (call on shutdown)."""
    global _driver
    if _driver is not None:
        with _driver_lock:
            if _driver is not None:
                _driver.close()
                _driver = None
                logger.info("memgraph.driver.closed")


atexit.register(close_memgraph_driver)


def memgraph_retry(max_attempts: int = 3):
    """Retry decorator for Memgraph operations on stale connections.

    On connection error: resets the driver singleton so the next call
    creates a fresh connection. Catches ServiceUnavailable, SessionExpired,
    BrokenPipeError, ConnectionError, and generic errors with connection-
    related messages.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except (ServiceUnavailable, SessionExpired,
                        BrokenPipeError, ConnectionError) as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        logger.warning("memgraph.retry", func=func.__name__,
                                       attempt=attempt + 1, error=str(e))
                        close_memgraph_driver()
                except Exception as e:
                    if "broken pipe" in str(e).lower() or "connection" in str(e).lower():
                        last_error = e
                        if attempt < max_attempts - 1:
                            logger.warning("memgraph.retry", func=func.__name__,
                                           attempt=attempt + 1, error=str(e))
                            close_memgraph_driver()
                            continue
                    raise
            if last_error:
                raise last_error
        return wrapper
    return decorator


def extract_graph_from_text(text: str, max_text_length: int = 8000) -> dict:
    """Extract entities and relationships from text via LLM."""
    if len(text) > max_text_length:
        text = text[:max_text_length] + "..."
        logger.warning("memgraph.extract.truncated", max_len=max_text_length)

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
    content = ""
    for attempt in range(3):
        try:
            content = chat_completion(
                messages=[
                    {"role": "system",
                     "content": "You extract knowledge graphs from text. "
                     "Return only valid JSON. Use only these entity types: "
                     "Person, Organization, Project, Task, Technology, "
                     "Document, Concept, Service, Event, Location."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1, json_mode=True, timeout=120,
            )
            break
        except Exception as e:
            if attempt < 2:
                wait = 2 * (attempt + 1)
                logger.warning("memgraph.extract.retry", attempt=attempt + 1, wait=wait, error=str(e))
                time.sleep(wait)
            else:
                logger.error("memgraph.extract.failed", error=str(e))
                return {"entities": [], "relationships": []}

    content = content.strip()
    if "<think>" in content:
        parts = content.split("</think>")
        if len(parts) > 1:
            content = parts[-1].strip()
    if "```" in content:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if m:
            content = m.group(1).strip()
    if not content.startswith("{"):
        s, e = content.find("{"), content.rfind("}")
        if s != -1 and e != -1 and e > s:
            content = content[s:e + 1]
    if not content:
        return {"entities": [], "relationships": []}

    try:
        data = json.loads(content)
        raw_entities = data.get("entities", [])
        raw_relationships = data.get("relationships", [])

        # Post-process: normalize types, validate names, merge persons
        from metatron.storage.graph_entities import (
            is_role_not_person,
            is_valid_entity_name,
            normalize_entity_type,
            normalize_person_name,
        )

        entities: list[dict] = []
        merged_aliases: dict[str, str] = {}  # alias_name → canonical_name
        for ent in raw_entities:
            name = (ent.get("name") or "").strip()
            if not is_valid_entity_name(name):
                logger.debug("memgraph.extract.entity_filtered", name=name)
                continue
            ent_type = normalize_entity_type(ent.get("type", ""))

            # Reclassify roles/groups from Person → Organization
            if is_role_not_person(name, ent_type):
                logger.debug("memgraph.extract.role_reclassified",
                             name=name, old_type=ent_type)
                ent_type = "Organization"

            # Merge person name variants to canonical form
            if ent_type == "Person":
                canonical = normalize_person_name(name, ent_type)
                if canonical != name:
                    merged_aliases[name] = canonical
                    logger.debug("memgraph.extract.person_merged",
                                 original=name, canonical=canonical)
                    name = canonical

            ent["name"] = name
            ent["type"] = ent_type
            entities.append(ent)

        # Deduplicate entities after merging (same canonical name)
        seen_names: set[str] = set()
        deduped: list[dict] = []
        for ent in entities:
            if ent["name"] not in seen_names:
                seen_names.add(ent["name"])
                deduped.append(ent)
        entities = deduped

        # Filter relationships to only include valid entity names
        valid_names = {e["name"] for e in entities}
        relationships: list[dict] = []
        for rel in raw_relationships:
            src = (rel.get("source") or "").strip()
            tgt = (rel.get("target") or "").strip()
            # Resolve merged aliases in relationships too
            src = merged_aliases.get(src, src)
            tgt = merged_aliases.get(tgt, tgt)
            if src in valid_names and tgt in valid_names:
                rel["source"] = src
                rel["target"] = tgt
                relationships.append(rel)

        logger.info("memgraph.extract.ok",
                     entities=len(entities), rels=len(relationships),
                     filtered=len(raw_entities) - len(entities),
                     merged=len(merged_aliases))
        return {
            "entities": entities,
            "relationships": relationships,
            "merged_aliases": merged_aliases,
        }
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("memgraph.extract.parse_error", error=str(exc))
        return {"entities": [], "relationships": []}


@memgraph_retry()
def write_doc_graph_to_memgraph(
    text: str, file_name: str, user_id: str = "user",
    workspace_id: str | None = None,
    doc_label: str | None = None, upload_time: str | None = None,
    doc_date: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Extract graph from text and write document + entities to Memgraph."""
    workspace_id = _normalize_workspace_id(workspace_id)
    if doc_label is None:
        upload_time = upload_time or datetime.now(UTC).isoformat()
        doc_label = f"{workspace_id}:{user_id}:{file_name}:{upload_time}"
    elif upload_time is None:
        upload_time = datetime.now(UTC).isoformat()

    graph = extract_graph_from_text(text)
    entities = graph["entities"]
    relationships = graph["relationships"]
    merged_aliases: dict[str, str] = graph.get("merged_aliases", {})
    doc_id = doc_label
    edge_date = doc_date or upload_time
    logger.info("memgraph.write_doc", entities=len(entities), rels=len(relationships))

    driver = get_memgraph_driver()
    _ws = _esc(workspace_id)
    _uid = _esc(user_id)
    _did = _esc(doc_id)
    _fn = _esc(file_name)
    _ut = _esc(upload_time)
    _txt = _esc(text)
    _dl = _esc(doc_label)
    # Resolve access_groups from metadata (set by enterprise RBAC hook)
    access_groups = metadata.get("access_groups") if metadata else None
    _ag_clause = ""
    if access_groups:
        _ag_clause = f", d.access_groups={_esc_list(access_groups)}"

    with driver.session() as session:
        session.run(
            f"MERGE (u:User {{user_id: {_uid}, workspace_id: {_ws}}}) "
            f"MERGE (d:Document {{doc_id: {_did}}}) "
            f"SET d.file_name={_fn}, d.upload_time={_ut}, d.raw_text={_txt}, "
            f"d.doc_label={_dl}, d.workspace_id={_ws}, d.user_id={_uid}"
            f"{_ag_clause} "
            "MERGE (u)-[r:UPLOADED]->(d) "
            f"SET r.valid_from = {_ut}",
        )
        for ent in entities:
            name = ent.get("name")
            if not name:
                continue
            _name = _esc(name)
            _type = _esc(ent.get("type", "unknown"))
            session.run(
                f"MATCH (d:Document {{doc_id: {_did}}}) "
                f"MERGE (e:Entity {{name: {_name}, workspace_id: {_ws}}}) "
                f"SET e.type={_type}, e.user_id={_uid}, "
                f"e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [{_dl}] "
                f"WHEN {_dl} IN e.doc_labels THEN e.doc_labels "
                f"ELSE e.doc_labels + [{_dl}] END "
                "MERGE (d)-[r:MENTIONS]->(e) "
                f"SET r.valid_from = {_esc(edge_date)}",
            )
        for rel in relationships:
            _src = _esc(rel.get("source"))
            _tgt = _esc(rel.get("target"))
            _rt = _esc(rel.get("type"))
            session.run(
                f"MERGE (e1:Entity {{name: {_src}, workspace_id: {_ws}}}) "
                f"MERGE (e2:Entity {{name: {_tgt}, workspace_id: {_ws}}}) "
                f"SET e1.doc_labels = CASE WHEN e1.doc_labels IS NULL THEN [{_dl}] "
                f"WHEN {_dl} IN e1.doc_labels THEN e1.doc_labels ELSE e1.doc_labels + [{_dl}] END, "
                f"e2.doc_labels = CASE WHEN e2.doc_labels IS NULL THEN [{_dl}] "
                f"WHEN {_dl} IN e2.doc_labels THEN e2.doc_labels ELSE e2.doc_labels + [{_dl}] END "
                f"MERGE (e1)-[r:RELATION {{type: {_rt}, workspace_id: {_ws}}}]->(e2) "
                f"SET r.valid_from = {_esc(edge_date)}",
            )
        # Write ALIAS relationships for merged person names
        for alias_name, canonical_name in merged_aliases.items():
            if alias_name.lower().strip() == canonical_name.lower().strip():
                continue
            session.run(
                f"MERGE (a:Entity {{name: {_esc(alias_name)}, workspace_id: {_ws}}}) "
                "SET a.type = 'Person' "
                f"MERGE (c:Entity {{name: {_esc(canonical_name)}, workspace_id: {_ws}}}) "
                "MERGE (a)-[:ALIAS]->(c)",
            )
    logger.info("memgraph.write_doc.done", file_name=file_name, workspace_id=workspace_id)


@memgraph_retry()
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
    driver = get_memgraph_driver()
    _ws = _esc(workspace_id)
    _root = _esc(root_chunk_id)
    _dl = _esc(doc_label)

    with driver.session() as session:
        # Create root chunk node
        session.run(
            f"MERGE (r:Chunk {{chunk_id: {_root}, workspace_id: {_ws}}}) "
            f"SET r.chunk_type='root', r.doc_label={_dl}"
        )
        # Create child nodes and CHILD_OF edges
        for child_id in child_chunk_ids:
            _cid = _esc(child_id)
            session.run(
                f"MERGE (c:Chunk {{chunk_id: {_cid}, workspace_id: {_ws}}}) "
                f"SET c.chunk_type='child', c.doc_label={_dl} "
                f"WITH c "
                f"MATCH (r:Chunk {{chunk_id: {_root}, workspace_id: {_ws}}}) "
                f"MERGE (c)-[:CHILD_OF]->(r)"
            )

    logger.info(
        "memgraph.chunk_hierarchy.done",
        root=root_chunk_id,
        children=len(child_chunk_ids),
        workspace_id=workspace_id,
    )


@memgraph_retry()
def delete_workspace_graph(workspace_id: str) -> None:
    """Delete all graph data for a specific workspace. WARNING: permanent."""
    driver = get_memgraph_driver()
    with driver.session() as session:
        session.run(
            f"MATCH (n) WHERE n.workspace_id = {_esc(workspace_id)} DETACH DELETE n",
        )
    logger.info("memgraph.workspace.deleted", workspace_id=workspace_id)
