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


def _review_comments_md(comments: list[dict]) -> list[str]:
    lines: list[str] = []
    if comments:
        lines += ["## Review Comments", ""]
        for c in comments:
            path = c.get("path", "")
            head = f"**{c.get('author', '')}**"
            if path:
                head += f" on `{path}`"
            head += f" ({c.get('created_at', '')}):"
            lines += [head, c.get("body", ""), ""]
    return lines


def pr_to_markdown(pr: dict, slug: str) -> str:
    """Render a pull-request input dict to Markdown."""
    number = pr.get("number", "")
    lines = [f"# [{slug} PR#{number}] {pr.get('title', '')}", ""]
    lines.append(f"**State:** {pr.get('state', '')}")
    lines.append(f"**Merged:** {'yes' if pr.get('merged') else 'no'}")
    if pr.get("base") or pr.get("head"):
        lines.append(f"**Branch:** {pr.get('head', '')} → {pr.get('base', '')}")
    if pr.get("user"):
        lines.append(f"**Author:** {pr['user']}")
    if pr.get("labels"):
        lines.append(f"**Labels:** {_csv(pr['labels'])}")
    lines.append("")
    if pr.get("body"):
        lines += ["## Description", "", pr["body"], ""]
    lines += _comments_md(pr.get("comments", []))
    lines += _review_comments_md(pr.get("review_comments", []))
    return "\n".join(lines)


def pr_to_document(pr: dict, owner: str, repo: str, workspace_id: str) -> Document:
    """Convert a pull-request input dict to a Document."""
    number = pr.get("number", "")
    slug = f"{owner}/{repo}"
    metadata = {
        "repo": slug,
        "type": "github_pr",
        "number": str(number),
        "state": pr.get("state", ""),
        "merged": "true" if pr.get("merged") else "false",
        "base": pr.get("base", ""),
        "head": pr.get("head", ""),
        "labels": _csv(pr.get("labels")),
        "author": pr.get("user", ""),
        "created_at_str": pr.get("created_at", ""),
        "updated_at_str": pr.get("updated_at", ""),
        "closed_at_str": pr.get("closed_at", ""),
    }
    created = _parse_dt(pr.get("created_at"))
    updated = _parse_dt(pr.get("updated_at"))
    return Document(
        source_type="github",
        source_id=f"gh-pr-{owner}-{repo}-{number}",
        workspace_id=workspace_id,
        title=f"[{slug} PR#{number}] {pr.get('title', '')}",
        content=pr_to_markdown(pr, slug),
        url=pr.get("html_url", ""),
        author=pr.get("user", ""),
        metadata=metadata,
        **({"created_at": created} if created else {}),
        **({"updated_at": updated} if updated else {}),
    )
