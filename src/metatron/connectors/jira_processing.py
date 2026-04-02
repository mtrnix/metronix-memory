"""Jira issue processing — ADF extraction, structured parsing, Markdown conversion.

Migrated from PoC: get_data_from_rabbitmq.py (process_jira_message, jira_to_markdown, extract_adf_text)
"""

from __future__ import annotations

import json

import structlog

logger = structlog.get_logger()


def extract_adf_text(adf_node) -> str:  # noqa: ANN001
    """Extract plain text from Atlassian Document Format (ADF).

    ADF is used in Jira Cloud for description and comment bodies.
    Recursively walks the ADF tree and concatenates text nodes.
    """
    if adf_node is None:
        return ""
    if isinstance(adf_node, str):
        return adf_node
    if isinstance(adf_node, dict):
        if adf_node.get("type") == "text":
            return adf_node.get("text", "")
        content = adf_node.get("content", [])
        texts = [extract_adf_text(child) for child in content]
        block_types = {
            "paragraph",
            "heading",
            "bulletList",
            "orderedList",
            "listItem",
            "codeBlock",
        }
        if adf_node.get("type") in block_types:
            return "\n".join(filter(None, texts)) + "\n"
        return "".join(texts)
    if isinstance(adf_node, list):
        return "".join(extract_adf_text(item) for item in adf_node)
    return ""


def process_jira_issue(data: dict | bytes | str) -> dict:
    """Parse a Jira API issue response into a structured dict.

    Handles both raw JSON (bytes/str) and pre-parsed dict input.
    Extracts description from ADF, comments, and changelog.
    """
    if isinstance(data, (bytes, str)):
        raw = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        data = json.loads(raw)

    fields = data.get("fields", {})

    # Description: ADF dict (v2) or plain text string (v3)
    description_raw = fields.get("description")
    if isinstance(description_raw, dict):
        description_text = extract_adf_text(description_raw).strip()
    elif isinstance(description_raw, str):
        description_text = description_raw.strip()
    else:
        description_text = ""

    comments_data = fields.get("comment", {}).get("comments", [])
    comments = []
    for c in comments_data:
        author = c.get("author", {}).get("displayName", "Unknown")
        created = c.get("created", "")
        body_raw = c.get("body")
        # Comment body: ADF dict (v2) or plain text string (v3)
        if isinstance(body_raw, dict):
            text = extract_adf_text(body_raw).strip()
        elif isinstance(body_raw, str):
            text = body_raw.strip()
        else:
            text = ""
        comments.append({"author": author, "created": created, "text": text})

    changelog_histories = data.get("changelog", {}).get("histories", [])
    changes = []
    for h in changelog_histories:
        author = h.get("author", {}).get("displayName", "Unknown")
        created = h.get("created", "")
        for item in h.get("items", []):
            changes.append(
                {
                    "author": author,
                    "created": created,
                    "field": item.get("field", ""),
                    "from": item.get("fromString", ""),
                    "to": item.get("toString", ""),
                }
            )

    return {
        "id": data.get("id"),
        "key": data.get("key"),
        "summary": fields.get("summary", ""),
        "status": fields.get("status", {}).get("name", ""),
        "assignee": fields.get("assignee", {}).get("displayName")
        if fields.get("assignee")
        else None,
        "assignee_email": fields.get("assignee", {}).get("emailAddress")
        if fields.get("assignee")
        else None,
        "reporter": fields.get("reporter", {}).get("displayName")
        if fields.get("reporter")
        else None,
        "reporter_email": fields.get("reporter", {}).get("emailAddress")
        if fields.get("reporter")
        else None,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "resolutiondate": fields.get("resolutiondate"),
        "priority": fields.get("priority", {}).get("name") if fields.get("priority") else None,
        "issuetype": fields.get("issuetype", {}).get("name") if fields.get("issuetype") else None,
        "description": description_text,
        "comments": comments,
        "changes": changes,
    }


def jira_issue_to_markdown(jira_data: dict) -> str:
    """Convert a structured Jira issue dict to Markdown text for embedding."""
    lines = [f"# [{jira_data['key']}] {jira_data['summary']}", ""]
    lines.append(f"**Status:** {jira_data['status']}")
    if jira_data.get("issuetype"):
        lines.append(f"**Type:** {jira_data['issuetype']}")
    if jira_data.get("priority"):
        lines.append(f"**Priority:** {jira_data['priority']}")
    if jira_data.get("assignee"):
        lines.append(f"**Assignee:** {jira_data['assignee']}")
    if jira_data.get("reporter"):
        lines.append(f"**Reporter:** {jira_data['reporter']}")
    if jira_data.get("created"):
        lines.append(f"**Created:** {jira_data['created']}")
    if jira_data.get("updated"):
        lines.append(f"**Updated:** {jira_data['updated']}")
    lines.append("")

    if jira_data.get("description"):
        lines += ["## Description", "", jira_data["description"], ""]
    if jira_data.get("comments"):
        lines += ["## Comments", ""]
        for c in jira_data["comments"]:
            lines += [f"**{c['author']}** ({c['created']}):", c["text"], ""]
    if jira_data.get("changes"):
        lines += ["## Changelog", ""]
        for ch in jira_data["changes"][-10:]:
            lines.append(
                f"- {ch['created']}: {ch['author']} changed **{ch['field']}**: {ch['from']} → {ch['to']}"
            )
        lines.append("")

    return "\n".join(lines)
