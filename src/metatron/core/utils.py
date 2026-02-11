"""Shared utility functions for text normalization and document labelling."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional


def normalize_text(text: str) -> str:
    """Remove invalid characters (surrogates, etc.)."""
    return text.encode("utf-8", "ignore").decode("utf-8")


def normalize_workspace_id(workspace_id: str | None = None) -> str:
    """Normalize workspace ID to canonical form.

    Returns the default workspace ID for *None* / ``"default"``,
    otherwise strips whitespace.
    """
    if workspace_id is None or workspace_id == "default":
        from metatron.core.config import Settings

        return Settings().default_workspace_id
    return workspace_id.strip()


def build_doc_label(
    source_id: str,
    user_id: str = "user",
    workspace_id: Optional[str] = None,
    upload_time: Optional[str] = None,
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
