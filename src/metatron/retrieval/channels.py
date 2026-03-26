"""Independent recall channels for the retrieval pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from metatron.core.config import Settings

import structlog

logger = structlog.get_logger(__name__)


class ScoredResult(TypedDict):
    """Single chunk result from a recall channel."""

    chunk_id: str
    doc_label: str
    score: float
    memory: dict


@dataclass
class RecallContext:
    """Shared context passed to every recall channel."""

    original_query: str
    translated_query: str
    expanded_query: str
    detected_language: str
    workspace_id: str
    access_filter: dict | None
    settings: Settings | None
    extracted_jira_keys: list[str]
    extracted_title_entities: list[str]
    extracted_dates: tuple | None
    detected_person: list[str]  # Resolved full names from AliasRegistry (empty if none)
    is_activity_query: bool


def merge_channels(channel_results: list[list[ScoredResult]]) -> list[ScoredResult]:
    """Merge results from multiple channels, deduplicate by chunk_id.

    If the same chunk appears from multiple channels, keep the entry
    with the highest score. Sort by score descending.
    """
    best: dict[str, ScoredResult] = {}
    for results in channel_results:
        for r in results:
            cid = r["chunk_id"]
            if cid not in best or r["score"] > best[cid]["score"]:
                best[cid] = r
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)
