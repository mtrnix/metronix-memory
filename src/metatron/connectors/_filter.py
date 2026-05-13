"""Shared sub-minute cursor filter for connectors (MTRNIX-332).

JQL (Jira) and CQL (Confluence) both support only minute-resolution date
filters (``yyyy-MM-dd HH:mm``). When the cursor is, say, ``22:09:40``, the
server-side filter ``>= "22:09"`` (Jira) or ``> "22:09"`` (Confluence) still
matches docs updated 22:09:00-22:09:59 — so a doc updated in the same minute
as the cursor stamp gets re-emitted on every sync until the cursor's minute
advances past it. This module gives the connectors a precise post-filter
they can apply with the raw item's ``updated`` field to drop those boundary
docs.

Both helpers are defensive: a missing or unparseable timestamp returns the
"keep" verdict (``True``) — safer to over-fetch one extra doc than to
silently lose it through a partially-typed dict from Atlassian's API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_iso_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO8601 timestamp (with ``Z`` or numeric offset) to UTC-aware
    ``datetime``. Returns ``None`` if the input is missing, not a string, or
    unparseable."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_strictly_after(raw_timestamp: Any, since: datetime | None) -> bool:
    """Return ``True`` if the parsed timestamp is strictly greater than the
    cursor.

    Returns ``True`` (= keep the doc) when ``since`` is ``None`` (initial
    sync), the timestamp is missing, or the timestamp is unparseable. Only
    drops the doc when we are *certain* its update predates or equals the
    cursor.
    """
    if since is None:
        return True
    ts = parse_iso_timestamp(raw_timestamp)
    if ts is None:
        return True
    return ts > since
