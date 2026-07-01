"""GitHub content processing — raw API dicts → Markdown + Document.

Pure and network-free (mirrors jira_processing / notion_processing). The
connector builds plain input dicts from PyGithub objects and calls these
functions; nothing here touches the network.
"""

from __future__ import annotations

from datetime import datetime

from metronix.core.models import Document


def _csv(values: list[str] | None) -> str:
    """Join non-empty string values with ', '."""
    return ", ".join(v for v in (values or []) if v)


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp (``Z`` or offset) to an aware datetime.

    Returns None if the value is missing or unparseable.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _comments_md(comments: list[dict]) -> list[str]:
    lines: list[str] = []
    if comments:
        lines += ["## Comments", ""]
        for c in comments:
            lines += [
                f"**{c.get('author', '')}** ({c.get('created_at', '')}):",
                c.get("body", ""),
                "",
            ]
    return lines


def issue_to_markdown(issue: dict, slug: str) -> str:
    """Render an issue input dict to Markdown."""
    number = issue.get("number", "")
    lines = [f"# [{slug}#{number}] {issue.get('title', '')}", ""]
    lines.append(f"**State:** {issue.get('state', '')}")
    if issue.get("user"):
        lines.append(f"**Author:** {issue['user']}")
    if issue.get("labels"):
        lines.append(f"**Labels:** {_csv(issue['labels'])}")
    if issue.get("assignees"):
        lines.append(f"**Assignees:** {_csv(issue['assignees'])}")
    lines.append("")
    if issue.get("body"):
        lines += ["## Description", "", issue["body"], ""]
    lines += _comments_md(issue.get("comments", []))
    return "\n".join(lines)


def issue_to_document(issue: dict, owner: str, repo: str, workspace_id: str) -> Document:
    """Convert an issue input dict to a Document."""
    number = issue.get("number", "")
    slug = f"{owner}/{repo}"
    metadata = {
        "repo": slug,
        "type": "github_issue",
        "number": str(number),
        "state": issue.get("state", ""),
        "labels": _csv(issue.get("labels")),
        "assignees": _csv(issue.get("assignees")),
        "author": issue.get("user", ""),
        "created_at_str": issue.get("created_at", ""),
        "updated_at_str": issue.get("updated_at", ""),
        "closed_at_str": issue.get("closed_at", ""),
    }
    created = _parse_dt(issue.get("created_at"))
    updated = _parse_dt(issue.get("updated_at"))
    return Document(
        source_type="github",
        source_id=f"gh-issue-{owner}-{repo}-{number}",
        workspace_id=workspace_id,
        title=f"[{slug}#{number}] {issue.get('title', '')}",
        content=issue_to_markdown(issue, slug),
        url=issue.get("html_url", ""),
        author=issue.get("user", ""),
        metadata=metadata,
        **({"created_at": created} if created else {}),
        **({"updated_at": updated} if updated else {}),
    )
