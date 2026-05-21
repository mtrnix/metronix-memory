"""Pure functions for ASOC entity → Document mapping.

No I/O, no httpx. All functions are stateless and deterministic.
Handles 10 ASOC entity types (canonical names per ASOC analytics docs):
    project, layer, issue, comment, issue_history, scan_result,
    sbom, dependency, gate, event.

Backward-compat alias: ``quality_gate`` → ``gate`` (existing indexed documents
with entity_type=quality_gate are still accepted in all dicts and handlers).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, cast

# ---------------------------------------------------------------------------
# Severity table
# ---------------------------------------------------------------------------

_SEVERITY_LABELS: dict[int, str] = {
    -1: "informational",
    1: "low",
    2: "medium",
    3: "high",
    4: "critical",
}
_SEVERITY_UNKNOWN = "unknown"


def severity_to_label(value: int | None) -> str:
    """Map ASOC integer severity to a human-readable label.

    ASOC encodes severity as -1 (informational), 1-4 (low/medium/high/critical).
    Returns ``"unknown"`` for ``None`` or unmapped values.
    """
    if value is None:
        return _SEVERITY_UNKNOWN
    return _SEVERITY_LABELS.get(value, _SEVERITY_UNKNOWN)


# ---------------------------------------------------------------------------
# Deterministic document ID
# ---------------------------------------------------------------------------


def deterministic_document_id(entity_type: str, entity_id: str, content: str) -> str:
    """Build a stable, content-sensitive document ID.

    Combining entity_type + entity_id + SHA-1 of content ensures:
    - Same entity → same ID (idempotent upserts).
    - Content change → different ID (forces re-index).

    The outer SHA-256 (truncated to 32 hex chars) avoids raw SHA-1 in the id
    field while keeping the string short enough for most DBs.
    """
    content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]  # noqa: S324
    composite = f"{entity_type}:{entity_id}:{content_hash}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Shared date parser
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO8601 string or pass through an existing datetime.

    Returns ``None`` for missing or unparseable values.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Per-entity handlers (_HANDLERS)
# ---------------------------------------------------------------------------


def _process_project(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("name", ""),
        "description": raw.get("description", ""),
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at")),
    }


def _process_layer(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("name", ""),
        "description": raw.get("description", ""),
        "kind": raw.get("kind", ""),
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at")),
    }


def _process_issue(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "severity": raw.get("severity"),
        "severity_label": severity_to_label(raw.get("severity")),
        "status": raw.get("status", ""),
        "layer_id": str(raw["layer_id"]) if raw.get("layer_id") is not None else None,
        "view_id": raw.get("view_id"),
        "author": raw.get("created_by", ""),
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at")),
    }


def _process_comment(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": "",
        "body": raw.get("body", ""),
        "author": raw.get("author", ""),
        "issue_id": str(raw["issue_id"]) if raw.get("issue_id") is not None else None,
        "issue_view_id": raw.get("issue_view_id"),
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at")),
    }


def _process_issue_history(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": "",
        "field": raw.get("field", ""),
        "old_value": raw.get("old_value"),
        "new_value": raw.get("new_value"),
        "author": raw.get("changed_by", ""),
        "issue_id": str(raw["issue_id"]) if raw.get("issue_id") is not None else None,
        "issue_view_id": raw.get("issue_view_id"),
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at") or raw.get("created_at")),
    }


def _process_scan_result(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("name", raw.get("scan_type", "")),
        "scan_type": raw.get("scan_type", ""),
        "status": raw.get("status", ""),
        "issue_count": raw.get("issue_count"),
        "layer_id": str(raw["layer_id"]) if raw.get("layer_id") is not None else None,
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at") or raw.get("created_at")),
    }


def _process_sbom(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("name", "SBOM"),
        "format": raw.get("format", ""),
        "version": raw.get("version", ""),
        "layer_id": str(raw["layer_id"]) if raw.get("layer_id") is not None else None,
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at") or raw.get("created_at")),
    }


def _process_dependency(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("name", ""),
        "version": raw.get("version", ""),
        "license": raw.get("license", ""),
        "risk_level": raw.get("risk_level"),
        "layer_id": str(raw["layer_id"]) if raw.get("layer_id") is not None else None,
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at") or raw.get("created_at")),
    }


def _process_gate(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("name", "Quality Gate"),
        "status": raw.get("status", ""),
        "conditions": raw.get("conditions", []),
        "project_id": str(raw["project_id"]) if raw.get("project_id") is not None else None,
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at") or raw.get("created_at")),
    }


# Backward-compat alias — existing callers + documents with entity_type=quality_gate still work.
_process_quality_gate = _process_gate


def _process_event(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(raw["id"]),
        "title": raw.get("event_type", "event"),
        "event_type": raw.get("event_type", ""),
        "payload": raw.get("payload", {}),
        "actor": raw.get("actor", ""),
        "project_id": str(raw["project_id"]) if raw.get("project_id") is not None else None,
        "created_at": _parse_dt(raw.get("created_at")),
        "updated_at": _parse_dt(raw.get("updated_at") or raw.get("created_at")),
    }


_HANDLERS: dict[str, Any] = {
    "project": _process_project,
    "layer": _process_layer,
    "issue": _process_issue,
    "comment": _process_comment,
    "issue_history": _process_issue_history,
    "scan_result": _process_scan_result,
    "sbom": _process_sbom,
    "dependency": _process_dependency,
    # "gate" is the canonical ASOC entity_type per analytics docs.
    # "quality_gate" is kept as a backward-compat alias (existing indexed docs).
    "gate": _process_gate,
    "quality_gate": _process_quality_gate,
    "event": _process_event,
}


def process_asoc_entity(entity_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw ASOC payload into a structured dict.

    Returned dict always contains: ``entity_id``, ``title`` (may be empty),
    ``created_at``, ``updated_at``, plus entity-specific fields.

    Raises:
        ValueError: If *entity_type* is not one of the 10 known types.
        KeyError: If the raw payload is missing a required field (e.g. ``"id"``).
    """
    handler = _HANDLERS.get(entity_type)
    if handler is None:
        raise ValueError(f"unknown entity_type: {entity_type!r}")
    return cast("dict[str, Any]", handler(raw))


# ---------------------------------------------------------------------------
# Markdown templates (_MARKDOWN_TEMPLATES)
# ---------------------------------------------------------------------------

_MARKDOWN_TEMPLATES: dict[str, Any] = {
    "project": lambda s: (
        f"# Project: {s['title']}\n\n"
        f"{s['description']}\n\n"
        f"Created: {s['created_at']}\n"
        f"Last updated: {s['updated_at']}"
    ),
    "layer": lambda s: (
        f"# Layer: {s['title']}\n\n"
        f"Kind: {s['kind']}\n\n"
        f"{s['description']}\n\n"
        f"Created: {s['created_at']}\n"
        f"Last updated: {s['updated_at']}"
    ),
    "issue": lambda s: (
        f"# Issue {s.get('view_id') or s['entity_id']}: {s['title']}\n\n"
        f"{s['description']}\n\n"
        f"Severity: {s['severity_label']} ({s['severity']})\n"
        f"Status: {s['status']}\n"
        f"Layer: {s['layer_id']}\n"
        f"Updated: {s['updated_at']}"
    ),
    "comment": lambda s: (
        f"# Comment on issue {s.get('issue_view_id') or s.get('issue_id', '')}\n\n"
        f"**Author:** {s['author']}\n\n"
        f"{s['body']}\n\n"
        f"Posted: {s['created_at']}"
    ),
    "issue_history": lambda s: (
        f"# History entry for issue {s.get('issue_view_id') or s.get('issue_id', '')}\n\n"
        f"**Author:** {s['author']}\n"
        f"**Field:** {s['field']}\n"
        f"**Change:** {s['old_value']} → {s['new_value']}\n\n"
        f"Changed: {s['created_at']}"
    ),
    "scan_result": lambda s: (
        f"# Scan: {s['title']}\n\n"
        f"Type: {s['scan_type']}\n"
        f"Status: {s['status']}\n"
        f"Issues found: {s['issue_count']}\n"
        f"Layer: {s['layer_id']}\n\n"
        f"Created: {s['created_at']}"
    ),
    "sbom": lambda s: (
        f"# SBOM: {s['title']}\n\n"
        f"Format: {s['format']}\n"
        f"Version: {s['version']}\n"
        f"Layer: {s['layer_id']}\n\n"
        f"Created: {s['created_at']}"
    ),
    "dependency": lambda s: (
        f"# Dependency: {s['title']}\n\n"
        f"Version: {s['version']}\n"
        f"License: {s['license']}\n"
        f"Risk level: {s['risk_level']}\n"
        f"Layer: {s['layer_id']}\n\n"
        f"Created: {s['created_at']}"
    ),
    # "gate" is canonical; "quality_gate" is a backward-compat alias.
    "gate": lambda s: (
        f"# Quality Gate: {s['title']}\n\n"
        f"Status: {s['status']}\n\n"
        f"Conditions: {s['conditions']}\n\n"
        f"Created: {s['created_at']}"
    ),
    "quality_gate": lambda s: (
        f"# Quality Gate: {s['title']}\n\n"
        f"Status: {s['status']}\n\n"
        f"Conditions: {s['conditions']}\n\n"
        f"Created: {s['created_at']}"
    ),
    "event": lambda s: (
        f"# Event: {s['event_type']}\n\n"
        f"Actor: {s['actor']}\n\n"
        f"Payload: {s['payload']}\n\n"
        f"Occurred: {s['created_at']}"
    ),
}


def entity_to_markdown(entity_type: str, structured: dict[str, Any]) -> str:
    """Build the ``Document.content`` textual representation for *entity_type*."""
    template_fn = _MARKDOWN_TEMPLATES[entity_type]
    return cast("str", template_fn(structured))


# ---------------------------------------------------------------------------
# Metadata builders (_METADATA_BUILDERS)
# ---------------------------------------------------------------------------

_METADATA_BUILDERS: dict[str, Any] = {
    "project": lambda s: {},
    "layer": lambda s: {"kind": s["kind"]},
    "issue": lambda s: {
        "layer_id": s["layer_id"],
        "severity": str(s["severity"]) if s["severity"] is not None else "",
        "severity_label": s["severity_label"],
        "status": s["status"],
        "view_id": s.get("view_id") or "",
    },
    "comment": lambda s: {
        "parent_entity_type": "issue",
        "parent_entity_id": s.get("issue_id") or "",
        "issue_id": s.get("issue_id") or "",
        "issue_view_id": s.get("issue_view_id") or "",
        "author": s.get("author") or "",
    },
    "issue_history": lambda s: {
        "parent_entity_type": "issue",
        "parent_entity_id": s.get("issue_id") or "",
        "issue_id": s.get("issue_id") or "",
        "issue_view_id": s.get("issue_view_id") or "",
        "field": s["field"],
    },
    "scan_result": lambda s: {
        "scan_type": s["scan_type"],
        "status": s["status"],
        "layer_id": s.get("layer_id") or "",
        "issue_count": str(s["issue_count"]) if s["issue_count"] is not None else "",
    },
    "sbom": lambda s: {
        "parent_entity_type": "layer",
        "parent_entity_id": s.get("layer_id") or "",
        "format": s["format"],
        "version": s["version"],
        "layer_id": s.get("layer_id") or "",
    },
    "dependency": lambda s: {
        "parent_entity_type": "layer",
        "parent_entity_id": s.get("layer_id") or "",
        "version": s["version"],
        "license": s["license"],
        "risk_level": str(s["risk_level"]) if s["risk_level"] is not None else "",
        "layer_id": s.get("layer_id") or "",
    },
    # "gate" is canonical; "quality_gate" is a backward-compat alias.
    "gate": lambda s: {
        "parent_entity_type": "project",
        "parent_entity_id": s.get("project_id") or "",
        "status": s["status"],
    },
    "quality_gate": lambda s: {
        "parent_entity_type": "project",
        "parent_entity_id": s.get("project_id") or "",
        "status": s["status"],
    },
    "event": lambda s: {
        "parent_entity_type": "project",
        "parent_entity_id": s.get("project_id") or "",
        "event_type": s["event_type"],
        "actor": s["actor"],
    },
}


def entity_to_metadata(
    entity_type: str, structured: dict[str, Any], project_id: str
) -> dict[str, Any]:
    """Build the ``Document.metadata`` dict (without ``asoc_url_hint`` — added separately)."""
    base: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": structured["entity_id"],
        "project_id": project_id,
        "updated_at": structured.get("updated_at"),
    }
    extra_fn = _METADATA_BUILDERS[entity_type]
    base.update(extra_fn(structured))
    return base


# ---------------------------------------------------------------------------
# URL hint builders (_URL_HINT_BUILDERS)
# ---------------------------------------------------------------------------

_URL_HINT_BUILDERS: dict[str, Any] = {
    "project": lambda s, m: f"/projects/{m['project_id']}",
    "layer": lambda s, m: f"/projects/{m['project_id']}/layers/{s['entity_id']}",
    "issue": lambda s, m: (
        f"/projects/{m['project_id']}/issues/{s.get('view_id') or s['entity_id']}"
    ),
    "comment": lambda s, m: (
        f"/projects/{m['project_id']}/issues/"
        f"{s.get('issue_view_id') or s.get('issue_id', '')}"
        f"/comments/{s['entity_id']}"
    ),
    "issue_history": lambda s, m: (
        f"/projects/{m['project_id']}/issues/"
        f"{s.get('issue_view_id') or s.get('issue_id', '')}"
        f"/history/{s['entity_id']}"
    ),
    "scan_result": lambda s, m: f"/projects/{m['project_id']}/scans/{s['entity_id']}",
    "sbom": lambda s, m: f"/projects/{m['project_id']}/sboms/{s['entity_id']}",
    "dependency": lambda s, m: f"/projects/{m['project_id']}/dependencies/{s['entity_id']}",
    # "gate" is canonical; "quality_gate" is a backward-compat alias.
    "gate": lambda s, m: f"/projects/{m['project_id']}/quality-gates/{s['entity_id']}",
    "quality_gate": lambda s, m: f"/projects/{m['project_id']}/quality-gates/{s['entity_id']}",
    "event": lambda s, m: f"/projects/{m['project_id']}/events/{s['entity_id']}",
}


def build_asoc_url_hint(
    entity_type: str, structured: dict[str, Any], metadata: dict[str, Any]
) -> str:
    """Build the URL-hint path for an entity.

    For ``comment`` and ``issue_history`` the path includes the parent issue's
    view_id (or raw id fallback) so the link points to a meaningful page.
    """
    builder = _URL_HINT_BUILDERS[entity_type]
    return cast("str", builder(structured, metadata))
