"""Title extraction from documents.

Extracts document titles from JSON message bodies (Confluence/Jira)
and from Markdown content, with fallback heuristics.
"""

from __future__ import annotations

import json
from typing import Optional, Union

import structlog

logger = structlog.get_logger()


def extract_title_from_body(body: Union[bytes, str]) -> Optional[str]:
    """Extract title from a JSON message body (Confluence/Jira).

    Args:
        body: Raw message body.

    Returns:
        Title string or ``None``.
    """
    try:
        if isinstance(body, bytes):
            raw = body.decode("utf-8", errors="replace")
        else:
            raw = body
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("title") or data.get("key")
    except Exception:
        pass
    return None


def extract_title_from_markdown(
    md: str,
    body: Union[bytes, str, None] = None,
) -> str:
    """Extract a document title with priority-based fallbacks.

    Priority:
    1. ``title`` from the JSON *body* (if provided)
    2. First ``# `` header in the Markdown
    3. First non-empty line (truncated to 80 chars)
    4. Default fallback ``"confluence_page"``

    Args:
        md: Markdown text.
        body: Optional raw message body for JSON title extraction.

    Returns:
        Document title.
    """
    title: Optional[str] = None

    if body:
        title = extract_title_from_body(body)

    if not title:
        lines = [line.strip() for line in md.splitlines()]
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        if not title:
            for line in lines:
                if line:
                    title = line[:80].strip()
                    break

    return title or "confluence_page"
