"""Shared utility functions for text normalization and document labelling."""

from __future__ import annotations

import re
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Agent id format — single source of truth
# ---------------------------------------------------------------------------

# An agent id flows into REST URL paths (``/agents/{id}/...``), the
# ``X-Agent-Id`` MCP header, and memory tool arguments. It must therefore be
# safe as a single URL path segment, so we restrict it to an unreserved
# character set rather than allowing arbitrary printable text. Generated ids
# (``uuid4().hex``) and dashed UUIDs both satisfy this, as do slugs like
# ``my-agent-001``.
AGENT_ID_MAX_LENGTH = 64
AGENT_ID_CHARS = r"A-Za-z0-9._-"
# Pattern string (no length bound) for pydantic ``Field(pattern=...)``; the
# length is enforced separately via ``max_length`` / ``min_length``. pydantic v2
# compiles this with the Rust ``regex`` engine, whose ``$`` already anchors at
# end-of-text (it does NOT match before a trailing newline).
AGENT_ID_PATTERN = rf"^[{AGENT_ID_CHARS}]+$"
# Use ``\A``/``\Z``, NOT ``^``/``$``: in Python's ``re`` engine ``$`` also
# matches just before a trailing newline, so ``"agent\n"`` would pass ``^...$``
# and defeat the path-safety guarantee (and diverge from the Rust-regex route
# check above). ``\A`` and ``\Z`` anchor strictly at start / end of string.
_AGENT_ID_REGEX = re.compile(rf"\A[{AGENT_ID_CHARS}]{{1,{AGENT_ID_MAX_LENGTH}}}\Z")


def is_valid_agent_id(value: str | None) -> bool:
    """Return True when ``value`` is a usable agent id.

    Valid ids are 1..64 characters drawn from ``A-Z a-z 0-9 . _ -``. Empty,
    over-length, or otherwise out-of-charset values (spaces, ``/``, ``%`` …)
    return False — those would break the REST ``/agents/{id}`` routes and the
    console even though they survive as an MCP header.
    """
    if not value:
        return False
    return _AGENT_ID_REGEX.match(value) is not None


def normalize_text(text: str) -> str:
    """Remove invalid characters (surrogates, etc.)."""
    return text.encode("utf-8", "ignore").decode("utf-8")


def normalize_workspace_id(workspace_id: str | None = None) -> str:
    """Normalize workspace ID to canonical form.

    Returns the default workspace ID for *None* / ``"default"``,
    otherwise strips whitespace.
    """
    if workspace_id is None or workspace_id == "default":
        from metronix.core.config import Settings

        return Settings().default_workspace_id
    return workspace_id.strip()


def build_doc_label(
    source_id: str,
    user_id: str = "user",
    workspace_id: str | None = None,
    upload_time: str | None = None,
) -> tuple[str, str]:
    """Build a stable document label to link vector and graph representations.

    Returns:
        Tuple of (doc_label, upload_time).
    """
    workspace_id = normalize_workspace_id(workspace_id)
    if upload_time is None:
        upload_time = datetime.now(UTC).isoformat()
    doc_label = f"{workspace_id}:{user_id}:{source_id}:{upload_time}"
    return doc_label, upload_time
