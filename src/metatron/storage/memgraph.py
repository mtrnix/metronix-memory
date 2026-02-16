"""Memgraph connection management + core graph write operations.

Migrated from PoC: db/memgraph.py (driver) + indexers/memgraph_workspace.py (write ops)
"""
# TODO: async migration
from __future__ import annotations

import atexit, json, re, time
from datetime import datetime, UTC
from threading import Lock
from typing import Optional

import structlog
from neo4j import GraphDatabase

from metatron.llm import chat_completion  # wired up when metatron.llm.chat_completion is available

logger = structlog.get_logger()

DEFAULT_WORKSPACE_ID = "MTRNIX"

_driver = None
_driver_lock = Lock()


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def get_memgraph_driver(uri: str = "bolt://localhost:7687",
                        user: str = "", password: str = ""):
    """Get shared Memgraph/Neo4j driver instance (singleton)."""
    global _driver
    if _driver is None:
        with _driver_lock:
            if _driver is None:
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

        # Post-process: normalize types and validate names
        from metatron.storage.graph_entities import normalize_entity_type, is_valid_entity_name

        entities: list[dict] = []
        for ent in raw_entities:
            name = (ent.get("name") or "").strip()
            if not is_valid_entity_name(name):
                logger.debug("memgraph.extract.entity_filtered", name=name)
                continue
            ent["name"] = name
            ent["type"] = normalize_entity_type(ent.get("type", ""))
            entities.append(ent)

        # Filter relationships to only include valid entity names
        valid_names = {e["name"] for e in entities}
        relationships: list[dict] = []
        for rel in raw_relationships:
            src = (rel.get("source") or "").strip()
            tgt = (rel.get("target") or "").strip()
            if src in valid_names and tgt in valid_names:
                rel["source"] = src
                rel["target"] = tgt
                relationships.append(rel)

        logger.info("memgraph.extract.ok",
                     entities=len(entities), rels=len(relationships),
                     filtered=len(raw_entities) - len(entities))
        return {"entities": entities, "relationships": relationships}
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("memgraph.extract.parse_error", error=str(exc))
        return {"entities": [], "relationships": []}


def write_doc_graph_to_memgraph(
    text: str, file_name: str, user_id: str = "user",
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None, upload_time: Optional[str] = None,
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
    doc_id = doc_label
    logger.info("memgraph.write_doc", entities=len(entities), rels=len(relationships))

    driver = get_memgraph_driver()
    with driver.session() as session:
        session.run(
            "MERGE (u:User {user_id: $user_id, workspace_id: $ws}) "
            "MERGE (d:Document {doc_id: $doc_id}) "
            "SET d.file_name=$fn, d.upload_time=$ut, d.raw_text=$txt, "
            "d.doc_label=$dl, d.workspace_id=$ws, d.user_id=$user_id "
            "MERGE (u)-[:UPLOADED]->(d)",
            {"user_id": user_id, "ws": workspace_id, "doc_id": doc_id,
             "fn": file_name, "ut": upload_time, "txt": text, "dl": doc_label},
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
                "MERGE (d)-[:MENTIONS]->(e)",
                {"doc_id": doc_id, "name": name, "type": ent.get("type", "unknown"),
                 "ws": workspace_id, "uid": user_id, "dl": doc_label},
            )
        for rel in relationships:
            session.run(
                "MERGE (e1:Entity {name: $src, workspace_id: $ws}) "
                "MERGE (e2:Entity {name: $tgt, workspace_id: $ws}) "
                "SET e1.doc_labels = CASE WHEN e1.doc_labels IS NULL THEN [$dl] "
                "WHEN $dl IN e1.doc_labels THEN e1.doc_labels ELSE e1.doc_labels + [$dl] END, "
                "e2.doc_labels = CASE WHEN e2.doc_labels IS NULL THEN [$dl] "
                "WHEN $dl IN e2.doc_labels THEN e2.doc_labels ELSE e2.doc_labels + [$dl] END "
                "MERGE (e1)-[r:RELATION {type: $rt, workspace_id: $ws}]->(e2)",
                {"src": rel.get("source"), "tgt": rel.get("target"),
                 "rt": rel.get("type"), "ws": workspace_id, "dl": doc_label},
            )
    logger.info("memgraph.write_doc.done", file_name=file_name, workspace_id=workspace_id)


def delete_workspace_graph(workspace_id: str) -> None:
    """Delete all graph data for a specific workspace. WARNING: permanent."""
    driver = get_memgraph_driver()
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.workspace_id = $ws DETACH DELETE n",
            {"ws": workspace_id},
        )
    logger.info("memgraph.workspace.deleted", workspace_id=workspace_id)
