"""Google Drive content processing — file metadata → Document.

Pure and network-free (mirrors github_processing / notion_processing). The
connector fetches file metadata + text via the Drive API and calls these
helpers; nothing here touches the network.
"""

from __future__ import annotations

from datetime import datetime

from metronix.core.models import Document

FOLDER_MIME = "application/vnd.google-apps.folder"

# Google-native MIME type -> (export MIME, human note). Only these are exported;
# everything else is either downloaded as bytes (binary path) or skipped.
_GOOGLE_EXPORT: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("text/markdown", "doc"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "sheet-first-tab-only"),
    "application/vnd.google-apps.presentation": ("text/plain", "slides"),
}


def export_format(mime: str) -> tuple[str, str] | None:
    """Return ``(export_mime, note)`` for a Google-native type, else ``None``."""
    return _GOOGLE_EXPORT.get(mime)


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp (``Z`` or offset) to an aware datetime."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _owner(meta: dict) -> str:
    """Owner-safe author: Shared-Drive items have no ``owners`` key.

    Never index ``owners[0]`` blindly — that would raise for Shared-Drive files
    and (via the connector's per-file guard) drop every such file.
    """
    owners = meta.get("owners") or []
    if not owners:
        return ""
    first = owners[0] or {}
    return first.get("displayName") or first.get("emailAddress") or ""


def build_document(meta: dict, text: str, workspace_id: str) -> Document:
    """Build a Document from Drive file metadata + already-extracted text."""
    author = _owner(meta)
    file_id = meta.get("id", "")
    updated = _parse_dt(meta.get("modifiedTime"))
    metadata = {
        "type": "gdrive",
        "file_id": file_id,
        "mime_type": meta.get("mimeType", ""),
        "owner": author,
    }
    return Document(
        source_type="gdrive",
        source_id=file_id,
        workspace_id=workspace_id,
        title=meta.get("name", ""),
        content=text,
        url=meta.get("webViewLink", ""),
        author=author,
        metadata=metadata,
        **({"updated_at": updated} if updated else {}),
    )
