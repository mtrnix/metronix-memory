"""Memgraph connection management + core graph write operations.

Migrated from PoC: db/memgraph.py (driver) + indexers/memgraph_workspace.py (write ops)
"""
# TODO: async migration
from __future__ import annotations

import atexit, json, re, time
from datetime import datetime, UTC
from functools import wraps
from threading import Lock
from typing import Optional

import structlog
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metatron.llm import chat_completion  # wired up when metatron.llm.chat_completion is available

logger = structlog.get_logger()

DEFAULT_WORKSPACE_ID = "MTRNIX"

_driver = None
_driver_lock = Lock()


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def get_memgraph_driver(uri: str | None = None,
                        user: str | None = None,
                        password: str | None = None):
    """Get shared Memgraph/Neo4j driver instance (singleton).

    Parameters default to values from Settings (env vars) when not provided.
    """
    global _driver
    if _driver is None:
        with _driver_lock:
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
            normalize_entity_type, is_valid_entity_name,
            is_role_not_person, normalize_person_name,
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
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None, upload_time: Optional[str] = None,
    doc_date: Optional[str] = None,
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
    with driver.session() as session:
        session.run(
            "MERGE (u:User {user_id: $user_id, workspace_id: $ws}) "
            "MERGE (d:Document {doc_id: $doc_id}) "
            "SET d.file_name=$fn, d.upload_time=$ut, d.raw_text=$txt, "
            "d.doc_label=$dl, d.workspace_id=$ws, d.user_id=$user_id "
            "MERGE (u)-[r:UPLOADED]->(d) "
            "SET r.valid_from = $vf",
            {"user_id": user_id, "ws": workspace_id, "doc_id": doc_id,
             "fn": file_name, "ut": upload_time, "txt": text, "dl": doc_label,
             "vf": upload_time},
        )
        for ent in entities:
            name = ent.get("name")
            if not name:
                continue
            session.run(
                "MATCH (d:Document {doc_id: $doc_id}) "
                "MERGE (e:Entity {name: $name, workspace_id: $ws}) "
                "SET e.type=$type, e.user_id=$uid, "
                "e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [$dl] "
                "WHEN $dl IN e.doc_labels THEN e.doc_labels "
                "ELSE e.doc_labels + [$dl] END "
                "MERGE (d)-[r:MENTIONS]->(e) "
                "SET r.valid_from = $vf",
                {"doc_id": doc_id, "name": name, "type": ent.get("type", "unknown"),
                 "ws": workspace_id, "uid": user_id, "dl": doc_label,
                 "vf": edge_date},
            )
        for rel in relationships:
            session.run(
                "MERGE (e1:Entity {name: $src, workspace_id: $ws}) "
                "MERGE (e2:Entity {name: $tgt, workspace_id: $ws}) "
                "SET e1.doc_labels = CASE WHEN e1.doc_labels IS NULL THEN [$dl] "
                "WHEN $dl IN e1.doc_labels THEN e1.doc_labels ELSE e1.doc_labels + [$dl] END, "
                "e2.doc_labels = CASE WHEN e2.doc_labels IS NULL THEN [$dl] "
                "WHEN $dl IN e2.doc_labels THEN e2.doc_labels ELSE e2.doc_labels + [$dl] END "
                "MERGE (e1)-[r:RELATION {type: $rt, workspace_id: $ws}]->(e2) "
                "SET r.valid_from = $vf",
                {"src": rel.get("source"), "tgt": rel.get("target"),
                 "rt": rel.get("type"), "ws": workspace_id, "dl": doc_label,
                 "vf": edge_date},
            )
        # Write ALIAS relationships for merged person names
        for alias_name, canonical_name in merged_aliases.items():
            if alias_name.lower().strip() == canonical_name.lower().strip():
                continue
            session.run(
                "MERGE (a:Entity {name: $alias, workspace_id: $ws}) "
                "SET a.type = 'Person' "
                "MERGE (c:Entity {name: $canonical, workspace_id: $ws}) "
                "MERGE (a)-[:ALIAS]->(c)",
                {"alias": alias_name, "canonical": canonical_name,
                 "ws": workspace_id},
            )
    logger.info("memgraph.write_doc.done", file_name=file_name, workspace_id=workspace_id)


@memgraph_retry()
def delete_workspace_graph(workspace_id: str) -> None:
    """Delete all graph data for a specific workspace. WARNING: permanent."""
    driver = get_memgraph_driver()
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.workspace_id = $ws DETACH DELETE n",
            {"ws": workspace_id},
        )
    logger.info("memgraph.workspace.deleted", workspace_id=workspace_id)
