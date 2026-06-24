from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from metronix.core.models import MemoryRecord, RawDocument
    from metronix.export.models import ExportScope

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_segment(raw: str, *, max_len: int = 80) -> str:
    """Return a filesystem-safe single path segment (no separators, no traversal)."""
    text = _UNSAFE.sub("-", (raw or "").strip())
    text = text.strip("-._")
    if text in ("", ".", ".."):
        text = "item-" + hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:8]
    return text[:max_len]


def unique_slug(raw: str, used: set[str], *, max_len: int = 80) -> str:
    """slugify_segment plus a stable hash suffix when the slug is already used."""
    base = slugify_segment(raw, max_len=max_len)
    candidate = base
    if candidate in used:
        suffix = hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:8]
        candidate = f"{base[: max_len - 9]}-{suffix}"
        n = 1
        while candidate in used:
            candidate = f"{base[: max_len - 11]}-{suffix}-{n}"
            n += 1
    used.add(candidate)
    return candidate


def _yaml_scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def render_agent_memory(agent_id: str, workspace_id: str, records: list[MemoryRecord]) -> str:
    lines = [
        f"# Agent memory: {agent_id}",
        "",
        f"- workspace: `{workspace_id}`",
        f"- agent_id: `{agent_id}`",
        f"- record_count: {len(records)}",
        "",
    ]
    for rec in records:
        lines += [
            "---",
            "",
            f"- kind: {rec.kind}",
            f"- scope: {rec.scope}",
            f"- status: {rec.status}",
            f"- importance_score: {rec.importance_score}",
            f"- created_at: {rec.created_at}",
            f"- updated_at: {rec.updated_at}",
            f"- tags: {', '.join(rec.tags) if rec.tags else '(none)'}",
            "",
            rec.content,
            "",
        ]
    return "\n".join(lines)


def render_document(doc: RawDocument) -> str:
    front = [
        "---",
        f"title: {_yaml_scalar(doc.title)}",
        f"source_id: {_yaml_scalar(doc.source_id)}",
        f"connector_type: {_yaml_scalar(doc.connector_type)}",
        f"url: {_yaml_scalar(doc.url)}",
        f"author: {_yaml_scalar(doc.author)}",
        f"status: {_yaml_scalar(str(doc.status))}",
        f"metadata: {_yaml_scalar(doc.metadata)}",
        "---",
        "",
    ]
    return "\n".join(front) + (doc.content or "")


def build_manifest(
    *,
    generated_at: datetime,
    scope: ExportScope,
    workspaces: list[str],
    agents: list[dict[str, Any]],
    counts: dict[str, Any],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "format_version": 1,
        "generated_at": generated_at.isoformat(),
        "scope": scope.to_dict(),
        "workspaces": workspaces,
        "counts": counts,
        "agents": agents,
        "limitations": limitations,
    }
