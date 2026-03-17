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
    memgraph_retry,
    DEFAULT_WORKSPACE_ID,
    _esc,
    _esc_list,
)

logger = structlog.get_logger()

_DONE_STATUSES = frozenset({
    "done", "closed", "resolved", "cancelled",
    "готово", "закрыто", "решено", "отменено",
})


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    if workspace_id is None or workspace_id == "default":
        return DEFAULT_WORKSPACE_ID
    return workspace_id.strip()


@memgraph_retry()
def write_jira_graph_to_memgraph(
    jira_data: dict,
    markdown_text: str,
    user_id: str = "user",
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None,
    upload_time: Optional[str] = None,
    skip_llm_extraction: bool = False,
    metadata: Optional[dict] = None,
) -> None:
    """Write Jira issue to Memgraph with workspace isolation.

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
    driver = get_memgraph_driver()

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
    _ag_clause = ""
    if access_groups:
        _ag_clause = f", j.access_groups={_esc_list(access_groups)}"

    with driver.session() as session:
        # Jira issue node
        session.run(
            f"MERGE (u:User {{user_id: {_esc(user_id)}, workspace_id: {_esc(workspace_id)}}}) "
            f"MERGE (j:JiraIssue {{issue_key: {_esc(issue_key)}, workspace_id: {_esc(workspace_id)}}}) "
            f"SET j.doc_id={_esc(doc_id)}, j.doc_label={_esc(doc_label)}, "
            f"j.summary={_esc(jira_data.get('summary', ''))}, "
            f"j.status={_esc(jira_data.get('status', ''))}, "
            f"j.priority={_esc(jira_data.get('priority'))}, "
            f"j.issuetype={_esc(jira_data.get('issuetype'))}, "
            f"j.assignee={_esc(jira_data.get('assignee'))}, "
            f"j.reporter={_esc(jira_data.get('reporter'))}, "
            f"j.created={_esc(jira_data.get('created'))}, "
            f"j.updated={_esc(jira_data.get('updated'))}, "
            f"j.description={_esc(jira_data.get('description', '')[:2000])}, "
            f"j.upload_time={_esc(upload_time)}, j.raw_text={_esc(markdown_text)}, "
            f"j.user_id={_esc(user_id)}"
            f"{_ag_clause} "
            "MERGE (u)-[:TRACKS]->(j)"
        )

        # Link assignee as Entity(type=person)
        _link_person(session, jira_data.get("assignee"), issue_key,
                     "ASSIGNED_TO", workspace_id, user_id, doc_label,
                     valid_from=valid_from, valid_to=valid_to_assigned)

        # Link reporter as Entity(type=person)
        _link_person(session, jira_data.get("reporter"), issue_key,
                     "REPORTED", workspace_id, user_id, doc_label,
                     valid_from=valid_from, valid_to=None)

        # Extract entities from description + comments (LLM-based, slow)
        if skip_llm_extraction:
            logger.debug("graph_jira.llm_skipped", issue_key=issue_key)
        else:
            text_for_graph = markdown_text[:6000]
            if text_for_graph.strip():
                try:
                    graph = extract_graph_from_text(text_for_graph)
                    _write_jira_entities(session, graph, issue_key,
                                        workspace_id, user_id, doc_label,
                                        valid_from=valid_from)
                except Exception as e:
                    logger.warning("graph_jira.extract_failed", error=str(e))

    logger.info("graph_jira.written", issue_key=issue_key, workspace_id=workspace_id)


def _link_person(session, person_name: Optional[str], issue_key: str,
                 rel_type: str, workspace_id: str, user_id: str,
                 doc_label: str,
                 valid_from: Optional[str] = None,
                 valid_to: Optional[str] = None) -> None:
    """Link a person (assignee/reporter) to a Jira issue node."""
    if not person_name:
        return
    session.run(
        f"MATCH (j:JiraIssue {{issue_key: {_esc(issue_key)}, workspace_id: {_esc(workspace_id)}}}) "
        f"MERGE (p:Entity {{name: {_esc(person_name)}, workspace_id: {_esc(workspace_id)}}}) "
        f"SET p.type = CASE WHEN p.type IS NULL THEN 'person' ELSE p.type END, "
        f"p.user_id = {_esc(user_id)}, "
        f"p.doc_labels = CASE WHEN p.doc_labels IS NULL THEN [{_esc(doc_label)}] "
        f"WHEN {_esc(doc_label)} IN p.doc_labels THEN p.doc_labels "
        f"ELSE p.doc_labels + [{_esc(doc_label)}] END "
        f"MERGE (p)-[r:{rel_type}]->(j) "
        f"SET r.valid_from = {_esc(valid_from)}, r.valid_to = {_esc(valid_to)}"
    )


def _write_jira_entities(session, graph: dict, issue_key: str,
                         workspace_id: str, user_id: str,
                         doc_label: str,
                         valid_from: Optional[str] = None) -> None:
    """Write extracted entities and relationships for a Jira issue."""
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])

    for ent in entities:
        name = ent.get("name")
        if not name:
            continue
        session.run(
            f"MATCH (j:JiraIssue {{issue_key: {_esc(issue_key)}, workspace_id: {_esc(workspace_id)}}}) "
            f"MERGE (e:Entity {{name: {_esc(name)}, workspace_id: {_esc(workspace_id)}}}) "
            f"SET e.type = {_esc(ent.get('type', 'unknown'))}, e.user_id = {_esc(user_id)}, "
            f"e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [{_esc(doc_label)}] "
            f"WHEN {_esc(doc_label)} IN e.doc_labels THEN e.doc_labels "
            f"ELSE e.doc_labels + [{_esc(doc_label)}] END "
            f"MERGE (j)-[r:MENTIONS]->(e) "
            f"SET r.valid_from = {_esc(valid_from)}"
        )

    for rel in relationships:
        session.run(
            f"MERGE (e1:Entity {{name: {_esc(rel.get('source'))}, workspace_id: {_esc(workspace_id)}}}) "
            f"MERGE (e2:Entity {{name: {_esc(rel.get('target'))}, workspace_id: {_esc(workspace_id)}}}) "
            f"MERGE (e1)-[r:RELATION {{type: {_esc(rel.get('type'))}, workspace_id: {_esc(workspace_id)}}}]->(e2) "
            f"SET r.valid_from = {_esc(valid_from)}"
        )
