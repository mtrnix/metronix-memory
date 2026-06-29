"""Upload ingestion helpers — allowlist, parsing, and Document construction.

Single source of truth for which file formats Metronix can ingest via the
upload endpoints, mirroring the capabilities of ``ingestion/processors``.
"""

from __future__ import annotations

from pathlib import Path

from metronix.core.models import Document

ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".xlsx", ".csv", ".html", ".htm", ".txt", ".md"}
)


def is_allowed_upload(filename: str) -> bool:
    """Return True if ``filename``'s extension is in the upload allowlist."""
    return Path(filename).suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS


def parse_upload(filename: str, raw_bytes: bytes) -> str:
    """Extract plain/markdown text from uploaded file bytes by extension.

    Mirrors the per-type dispatch previously inlined in the legacy upload
    endpoint. Raises ValueError for unprocessable tabular content; callers
    treat any exception as a per-file failure.
    """
    from metronix.ingestion.processors import is_tabular_file, process_tabular_file
    from metronix.ingestion.processors.html import process_html

    lower = filename.lower()
    if lower.endswith(".pdf"):
        from metronix.ingestion.processors.pdf import extract_text_from_pdf

        return extract_text_from_pdf(raw_bytes, filename)
    if lower.endswith(".docx"):
        from metronix.ingestion.processors.office import extract_text_from_docx

        return extract_text_from_docx(raw_bytes)
    if is_tabular_file(filename):
        text, _meta = process_tabular_file(raw_bytes, filename)
        return text
    if lower.endswith((".html", ".htm")):
        text = raw_bytes.decode("utf-8", errors="replace")
        return process_html(text)
    return raw_bytes.decode("utf-8", errors="replace")


def build_upload_document(filename: str, text: str, user_id: str, workspace_id: str) -> Document:
    """Build a Document for an uploaded file, compatible with the connector pipeline."""
    return Document(
        workspace_id=workspace_id,
        source_type="upload",
        source_id=filename,
        title=filename,
        content=text,
        url="",
        author=user_id,
        source_role="user_upload",
    )
