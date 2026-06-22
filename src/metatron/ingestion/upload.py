"""Upload ingestion helpers — allowlist, parsing, and Document construction.

Single source of truth for which file formats Metatron can ingest via the
upload endpoints, mirroring the capabilities of ``ingestion/processors``.
"""

from __future__ import annotations

from pathlib import Path

ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".xlsx", ".csv", ".html", ".htm", ".txt", ".md"}
)


def is_allowed_upload(filename: str) -> bool:
    """Return True if ``filename``'s extension is in the upload allowlist."""
    return Path(filename).suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS
