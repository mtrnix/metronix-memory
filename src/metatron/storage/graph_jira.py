"""Jira-specific graph operations for Memgraph.

Writes Jira issues to the knowledge graph with workspace isolation,
linking issues to assignees, reporters, and extracted entities.

Migrated from PoC: metatron_experiments/metatron/indexers/memgraph_workspace.py
"""
# TODO: async migration
from __future__ import annotations

from datetime import datetime, UTC
from typing import Optional

import structlog

from metatron.storage.memgraph import (
    get_memgraph_driver,
    extract_graph_from_text,
    DEFAULT_WORKSPACE_ID,
)

logger = structlog.get_logger()


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


def write_jira_graph_to_memgraph(
    jira_data: dict,
    markdown_text: str,
    user_id: str = "user",
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None,
    upload_time: Optional[str] = None,
) -> None:
    """Write Jira issue to Memgraph with workspace isolation.

    Creates a :JiraIssue node, links participants (assignee, reporter),
    and extracts entities/relationships from the issue text.
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    issue_key = jira_data.get("key", "UNKNOWN")

    if doc_label is None:
        upload_time = upload_time or datetime.now(UTC).isoformat()
        doc_label = f"{workspace_id}:{user_id}:{issue_key}:{upload_time}"
    elif upload_time is None:
        upload_time = datetime.now(UTC).isoformat()

    doc_id = doc_label
    driver = get_memgraph_driver()

    with driver.session() as session:
        # Jira issue node
        session.run(
            "MERGE (u:User {user_id: $uid, workspace_id: $ws}) "
            "MERGE (j:JiraIssue {issue_key: $ik, workspace_id: $ws}) "
            "SET j.doc_id=$did, j.doc_label=$dl, j.summary=$sum, j.status=$st, "
            "j.priority=$pri, j.issuetype=$it, j.assignee=$asg, j.reporter=$rep, "
            "j.created=$cr, j.updated=$upd, j.description=$desc, "
            "j.upload_time=$ut, j.raw_text=$rt, j.user_id=$uid "
            "MERGE (u)-[:TRACKS]->(j)",
            {
                "uid": user_id, "ws": workspace_id, "did": doc_id, "dl": doc_label,
                "ik": issue_key, "sum": jira_data.get("summary", ""),
                "st": jira_data.get("status", ""), "pri": jira_data.get("priority"),
                "it": jira_data.get("issuetype"), "asg": jira_data.get("assignee"),
                "rep": jira_data.get("reporter"), "cr": jira_data.get("created"),
                "upd": jira_data.get("updated"),
                "desc": jira_data.get("description", "")[:2000],
                "ut": upload_time, "rt": markdown_text,
            },
        )

        # Link assignee as Entity(type=person)
        _link_person(session, jira_data.get("assignee"), issue_key,
                     "ASSIGNED_TO", workspace_id, user_id, doc_label)

        # Link reporter as Entity(type=person)
        _link_person(session, jira_data.get("reporter"), issue_key,
                     "REPORTED", workspace_id, user_id, doc_label)

        # Extract entities from description + comments
        text_for_graph = markdown_text[:6000]
        if text_for_graph.strip():
            try:
                graph = extract_graph_from_text(text_for_graph)
                _write_jira_entities(session, graph, issue_key,
                                    workspace_id, user_id, doc_label)
            except Exception as e:
                logger.warning("graph_jira.extract_failed", error=str(e))

    logger.info("graph_jira.written", issue_key=issue_key, workspace_id=workspace_id)


def _link_person(session, person_name: Optional[str], issue_key: str,
                 rel_type: str, workspace_id: str, user_id: str,
                 doc_label: str) -> None:
    """Link a person (assignee/reporter) to a Jira issue node."""
    if not person_name:
        return
    session.run(
        "MATCH (j:JiraIssue {issue_key: $ik, workspace_id: $ws}) "
        "MERGE (p:Entity {name: $name, workspace_id: $ws}) "
        "SET p.type = COALESCE(p.type, 'person'), p.user_id = $uid, "
        "p.doc_labels = CASE WHEN p.doc_labels IS NULL THEN [$dl] "
        "WHEN $dl IN p.doc_labels THEN p.doc_labels "
        "ELSE p.doc_labels + [$dl] END "
        f"MERGE (p)-[:{rel_type}]->(j)",
        {"ik": issue_key, "name": person_name, "ws": workspace_id,
         "uid": user_id, "dl": doc_label},
    )


def _write_jira_entities(session, graph: dict, issue_key: str,
                         workspace_id: str, user_id: str,
                         doc_label: str) -> None:
    """Write extracted entities and relationships for a Jira issue."""
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])

    for ent in entities:
        name = ent.get("name")
        if not name:
            continue
        session.run(
            "MATCH (j:JiraIssue {issue_key: $ik, workspace_id: $ws}) "
            "MERGE (e:Entity {name: $name, workspace_id: $ws}) "
            "SET e.type = $type, e.user_id = $uid, "
            "e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [$dl] "
            "WHEN $dl IN e.doc_labels THEN e.doc_labels "
            "ELSE e.doc_labels + [$dl] END "
            "MERGE (j)-[:MENTIONS]->(e)",
            {"ik": issue_key, "name": name, "type": ent.get("type", "unknown"),
             "ws": workspace_id, "uid": user_id, "dl": doc_label},
        )

    for rel in relationships:
        session.run(
            "MERGE (e1:Entity {name: $src, workspace_id: $ws}) "
            "MERGE (e2:Entity {name: $tgt, workspace_id: $ws}) "
            "MERGE (e1)-[r:RELATION {type: $rt, workspace_id: $ws}]->(e2)",
            {"src": rel.get("source"), "tgt": rel.get("target"),
             "rt": rel.get("type"), "ws": workspace_id},
        )
