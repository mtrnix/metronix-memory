"""Jira-specific graph operations for Neo4j.

Writes Jira issues to the knowledge graph with workspace isolation,
linking issues to assignees, reporters, and extracted entities.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from metronix.storage.neo4j_graph import (
    DEFAULT_WORKSPACE_ID,
    extract_graph_from_text,
    get_graph_driver,
    graph_retry,
)

logger = structlog.get_logger()

_DONE_STATUSES = frozenset(
    {
        "done",
        "closed",
        "resolved",
        "cancelled",
        "готово",
        "закрыто",
        "решено",
        "отменено",
    }
)


def _normalize_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


@graph_retry()
def write_jira_graph(
    jira_data: dict,
    markdown_text: str,
    user_id: str = "user",
    workspace_id: str | None = None,
    doc_label: str | None = None,
    upload_time: str | None = None,
    skip_llm_extraction: bool = False,
    metadata: dict | None = None,
) -> None:
    """Write Jira issue to Neo4j with workspace isolation.

    Creates a :JiraIssue node, links participants (assignee, reporter),
    and extracts entities/relationships from the issue text.

    Args:
        skip_llm_extraction: If True, create JiraIssue node and person
            links but skip the LLM-based entity extraction (for short issues).
    """
    workspace_id = _normalize_workspace_id(workspace_id)
    issue_key = jira_data.get("key", "UNKNOWN")

    if doc_label is None:
        upload_time = upload_time or datetime.now(UTC).isoformat()
        doc_label = f"{workspace_id}:{user_id}:{issue_key}:{upload_time}"
    elif upload_time is None:
        upload_time = datetime.now(UTC).isoformat()

    doc_id = doc_label
    driver = get_graph_driver()

    # Compute temporal bounds
    valid_from = jira_data.get("created")
    resolved_str = jira_data.get("resolved_at")
    status = (jira_data.get("status") or "").strip().lower()
    valid_to_assigned = resolved_str or (
        jira_data.get("updated") if status in _DONE_STATUSES else None
    )

    # Resolve access_groups from metadata (set by enterprise RBAC hook)
    access_groups = metadata.get("access_groups") if metadata else None
    if not access_groups:
        access_groups = jira_data.get("access_groups")

    with driver.session() as session:
        # Jira issue node
        session.run(
            "MERGE (u:User {user_id: $uid, workspace_id: $ws}) "
            "MERGE (j:JiraIssue {issue_key: $ik, workspace_id: $ws}) "
            "SET j.doc_id = $doc_id, j.doc_label = $dl, "
            "    j.summary = $summary, j.status = $status, "
            "    j.priority = $priority, j.issuetype = $issuetype, "
            "    j.assignee = $assignee, j.reporter = $reporter, "
            "    j.created = $created, j.updated = $updated, "
            "    j.description = $description, "
            "    j.upload_time = $ut, j.raw_text = $raw_text, "
            "    j.user_id = $uid, j.access_groups = $ag "
            "MERGE (u)-[:TRACKS]->(j)",
            {
                "uid": user_id,
                "ws": workspace_id,
                "ik": issue_key,
                "doc_id": doc_id,
                "dl": doc_label,
                "summary": jira_data.get("summary", ""),
                "status": jira_data.get("status", ""),
                "priority": jira_data.get("priority"),
                "issuetype": jira_data.get("issuetype"),
                "assignee": jira_data.get("assignee"),
                "reporter": jira_data.get("reporter"),
                "created": jira_data.get("created"),
                "updated": jira_data.get("updated"),
                "description": (jira_data.get("description", "") or "")[:2000],
                "ut": upload_time,
                "raw_text": markdown_text,
                "ag": access_groups,
            },
        )

        # Link assignee as Entity(type=person)
        _link_person(
            session,
            jira_data.get("assignee"),
            issue_key,
            "ASSIGNED_TO",
            workspace_id,
            user_id,
            doc_label,
            valid_from=valid_from,
            valid_to=valid_to_assigned,
        )

        # Link reporter as Entity(type=person)
        _link_person(
            session,
            jira_data.get("reporter"),
            issue_key,
            "REPORTED",
            workspace_id,
            user_id,
            doc_label,
            valid_from=valid_from,
            valid_to=None,
        )

        # Extract entities from description + comments (LLM-based, slow)
        if skip_llm_extraction:
            logger.debug("graph_jira.llm_skipped", issue_key=issue_key)
        else:
            text_for_graph = markdown_text[:6000]
            if text_for_graph.strip():
                try:
                    graph = extract_graph_from_text(text_for_graph)
                    _write_jira_entities(
                        session,
                        graph,
                        issue_key,
                        workspace_id,
                        user_id,
                        doc_label,
                        valid_from=valid_from,
                    )
                except Exception as e:
                    logger.warning("graph_jira.extract_failed", error=str(e))

    logger.info("graph_jira.written", issue_key=issue_key, workspace_id=workspace_id)


def _link_person(
    session,
    person_name: str | None,
    issue_key: str,
    rel_type: str,
    workspace_id: str,
    user_id: str,
    doc_label: str,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> None:
    """Link a person (assignee/reporter) to a Jira issue node."""
    if not person_name:
        return
    session.run(
        f"MATCH (j:JiraIssue {{issue_key: $ik, workspace_id: $ws}}) "
        "MERGE (p:Entity {name: $pname, workspace_id: $ws}) "
        "SET p.type = CASE WHEN p.type IS NULL THEN 'person' ELSE p.type END, "
        "    p.user_id = $uid, "
        "    p.doc_labels = CASE WHEN p.doc_labels IS NULL THEN [$dl] "
        "    WHEN $dl IN p.doc_labels THEN p.doc_labels "
        "    ELSE p.doc_labels + [$dl] END "
        f"MERGE (p)-[r:{rel_type}]->(j) "
        "SET r.valid_from = $vf, r.valid_to = $vt",
        {
            "ik": issue_key,
            "ws": workspace_id,
            "pname": person_name,
            "uid": user_id,
            "dl": doc_label,
            "vf": valid_from,
            "vt": valid_to,
        },
    )


def _write_jira_entities(
    session,
    graph: dict,
    issue_key: str,
    workspace_id: str,
    user_id: str,
    doc_label: str,
    valid_from: str | None = None,
) -> None:
    """Write extracted entities and relationships for a Jira issue."""
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    mention_counts: dict[str, int] = graph.get("mention_counts", {})

    for ent in entities:
        name = ent.get("name")
        if not name:
            continue
        session.run(
            "MATCH (j:JiraIssue {issue_key: $ik, workspace_id: $ws}) "
            "MERGE (e:Entity {name: $name, workspace_id: $ws}) "
            "SET e.type = $etype, e.user_id = $uid, "
            "    e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [$dl] "
            "    WHEN $dl IN e.doc_labels THEN e.doc_labels "
            "    ELSE e.doc_labels + [$dl] END "
            "MERGE (j)-[r:MENTIONS]->(e) "
            "SET r.valid_from = $vf, r.mention_count = $mention_count",
            {
                "ik": issue_key,
                "ws": workspace_id,
                "name": name,
                "etype": ent.get("type", "unknown"),
                "uid": user_id,
                "dl": doc_label,
                "vf": valid_from,
                "mention_count": mention_counts.get(name, 1),
            },
        )

    for rel in relationships:
        session.run(
            "MERGE (e1:Entity {name: $src, workspace_id: $ws}) "
            "MERGE (e2:Entity {name: $tgt, workspace_id: $ws}) "
            "MERGE (e1)-[r:RELATION {type: $rtype, workspace_id: $ws}]->(e2) "
            "SET r.valid_from = $vf",
            {
                "src": rel.get("source"),
                "tgt": rel.get("target"),
                "ws": workspace_id,
                "rtype": rel.get("type"),
                "vf": valid_from,
            },
        )
