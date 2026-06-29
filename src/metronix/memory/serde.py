"""Serialization helpers for memory records.

Centralizes conversion from Qdrant payload dicts to MemoryRecord dataclasses
so both the search service (L3) and MemoryService (L4) share a single
reconstruction path.
"""

from __future__ import annotations

from typing import Any

from metronix.core.models import MemoryRecord, MemoryScope


def record_from_qdrant_payload(
    hit: dict[str, Any],
    workspace_id: str,
) -> MemoryRecord:
    """Reconstruct a MemoryRecord from a Qdrant payload dict.

    ``hit`` is either a search result (with top-level conveniences like
    ``record_id``/``content``/``agent_id``) or a scroll/get payload dict.
    Either shape works — ``payload`` keys are preferred, top-level keys fill
    in for search-result shape.
    """
    payload = hit.get("payload") or {}
    tags = hit.get("tags") or payload.get("tags") or []
    scope_raw = payload.get("scope") or hit.get("scope") or MemoryScope.PER_AGENT.value
    try:
        scope = MemoryScope(scope_raw)
    except ValueError:
        scope = MemoryScope.PER_AGENT
    # ``hit.get("id")`` fallback covers qdrant-client ``retrieve()`` results where
    # the canonical ID lives at the point level (point.id) and only the payload
    # keys land in the dict — ``record_id`` may not be present at the top level.
    return MemoryRecord(
        id=str(hit.get("record_id") or payload.get("record_id") or hit.get("id") or ""),
        workspace_id=str(payload.get("workspace_id") or workspace_id),
        agent_id=str(hit.get("agent_id") or payload.get("agent_id") or ""),
        scope=scope,
        source_type=str(payload.get("source_type") or ""),
        content=str(hit.get("content") or payload.get("content") or ""),
        tags=list(tags),
        importance_score=float(
            hit.get("importance_score") or payload.get("importance_score") or 0.0,
        ),
    )
