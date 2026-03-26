"""Independent recall channels for the retrieval pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from metatron.core.config import Settings

import structlog

from metatron.storage.graph_ops import get_doc_labels_by_entities, get_graph_entities
from metatron.storage.qdrant import get_hybrid_store

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
    workspace_id: str | None
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


def _qdrant_hit_to_scored(hit: dict) -> ScoredResult:
    """Convert a Qdrant store result (flat dict) to ScoredResult."""
    return ScoredResult(
        chunk_id=str(hit.get("id", "")),
        doc_label=hit.get("doc_label", ""),
        score=float(hit.get("score", 0.0)),
        memory=hit,
    )


def recall_dense(ctx: RecallContext) -> list[ScoredResult]:
    """Dense channel: RRF hybrid search (dense + sparse vectors)."""
    limit = ctx.settings.recall_top_n_dense if ctx.settings else 30
    try:
        store = get_hybrid_store(ctx.workspace_id)
        hits = store.hybrid_search(
            query=ctx.translated_query or ctx.expanded_query,
            limit=limit,
            filter_conditions=ctx.access_filter,
        )
        return [_qdrant_hit_to_scored(h) for h in hits[:limit]]
    except Exception:
        logger.error("recall_dense failed", workspace=ctx.workspace_id, exc_info=True)
        return []


def recall_exact(ctx: RecallContext) -> list[ScoredResult]:
    """Exact channel: Jira key lookup + title entity search."""
    limit = ctx.settings.recall_top_n_exact if ctx.settings else 10
    if not ctx.extracted_jira_keys and not ctx.extracted_title_entities:
        return []
    try:
        store = get_hybrid_store(ctx.workspace_id)
        hits: list[dict] = []

        if ctx.extracted_jira_keys:
            hits.extend(store.search_by_doc_labels(ctx.extracted_jira_keys))

        for entity in ctx.extracted_title_entities:
            title_hits = store.scroll_by_title(entity, limit=5)
            hits.extend(title_hits)

        seen_ids: set[str] = set()
        results: list[ScoredResult] = []
        for h in hits:
            hid = str(h.get("id", ""))
            if hid in seen_ids:
                continue
            seen_ids.add(hid)
            results.append(_qdrant_hit_to_scored(h))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    except Exception:
        logger.error("recall_exact failed", workspace=ctx.workspace_id, exc_info=True)
        return []


_ACTIVITY_STATUSES = ["In Progress", "В работе", "Selected for Development"]


def recall_metadata(ctx: RecallContext) -> list[ScoredResult]:
    """Metadata channel: date filters, person/assignee, activity status."""
    limit = ctx.settings.recall_top_n_metadata if ctx.settings else 10
    has_signal = ctx.extracted_dates or len(ctx.detected_person) > 0 or ctx.is_activity_query
    if not has_signal:
        return []
    try:
        store = get_hybrid_store(ctx.workspace_id)
        hits: list[dict] = []

        if ctx.extracted_dates:
            date_hits = store.search_by_date(ctx.extracted_dates, limit=limit)
            hits.extend(date_hits)

        # Person-specific: search by assignee for each resolved name (skips general status)
        if ctx.detected_person:
            for name in ctx.detected_person:
                assignee_hits = store.search_by_assignee(name, limit=limit)
                hits.extend(assignee_hits)
        elif ctx.is_activity_query:
            for status in _ACTIVITY_STATUSES:
                status_hits = store.search_by_status(status, limit=limit)
                hits.extend(status_hits)

        seen_ids: set[str] = set()
        results: list[ScoredResult] = []
        for h in hits:
            hid = str(h.get("id", ""))
            if hid in seen_ids:
                continue
            seen_ids.add(hid)
            results.append(_qdrant_hit_to_scored(h))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    except Exception:
        logger.error("recall_metadata failed", workspace=ctx.workspace_id, exc_info=True)
        return []


def recall_graph(ctx: RecallContext) -> list[ScoredResult]:
    """Graph channel: find related documents via entity graph traversal."""
    limit = ctx.settings.recall_top_n_graph if ctx.settings else 5
    try:
        query_for_ner = ctx.translated_query or ctx.original_query
        entities = get_graph_entities([query_for_ner], workspace_id=ctx.workspace_id)
        if not entities:
            return []

        entity_names = [e["name"] for e in entities if "name" in e]
        if not entity_names:
            return []

        # get_doc_labels_by_entities returns List[Dict] with "doc_label" key
        related = get_doc_labels_by_entities(entity_names, workspace_id=ctx.workspace_id)
        if not related:
            return []

        related_labels = [r["doc_label"] for r in related if "doc_label" in r]
        if not related_labels:
            return []

        store = get_hybrid_store(ctx.workspace_id)
        hits = store.search_by_doc_labels(related_labels, limit=limit)
        return [_qdrant_hit_to_scored(h) for h in hits[:limit]]
    except Exception:
        logger.error("recall_graph failed", workspace=ctx.workspace_id, exc_info=True)
        return []
