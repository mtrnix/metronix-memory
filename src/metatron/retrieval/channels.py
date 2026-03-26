"""Independent recall channels for the retrieval pipeline."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from metatron.core.config import Settings

import structlog

from metatron.storage.graph_ops import (
    get_doc_labels_by_entities,
    get_graph_entities,
    get_graph_relationships,
)
from metatron.storage.qdrant import get_hybrid_store

logger = structlog.get_logger(__name__)


class ScoredResult(TypedDict):
    """Single chunk result from a recall channel."""

    chunk_id: str
    doc_label: str
    score: float
    memory: dict
    channel: str


class MergedResult(TypedDict):
    """Result after merging across channels — preserves all channel info."""

    chunk_id: str
    doc_label: str
    memory: dict
    channels: list[str]
    channel_scores: dict[str, float]


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
    extracted_dates: tuple[str, ...] | None
    detected_person: list[str]  # Resolved full names from AliasRegistry (empty if none)
    is_activity_query: bool


def merge_channels(channel_results: list[list[ScoredResult]]) -> list[MergedResult]:
    """Merge results from multiple channels, preserving all channel scores.

    If the same chunk appears from multiple channels, all channel scores are kept.
    Memory payload is taken from the highest-scoring channel entry.
    Results are sorted by max channel score descending.
    """
    accumulator: dict[str, MergedResult] = {}
    best_score: dict[str, float] = {}

    for results in channel_results:
        for r in results:
            cid = r["chunk_id"]
            if cid not in accumulator:
                accumulator[cid] = MergedResult(
                    chunk_id=cid,
                    doc_label=r["doc_label"],
                    memory=r["memory"],
                    channels=[r["channel"]],
                    channel_scores={r["channel"]: r["score"]},
                )
                best_score[cid] = r["score"]
            else:
                merged = accumulator[cid]
                if r["channel"] not in merged["channels"]:
                    merged["channels"].append(r["channel"])
                merged["channel_scores"][r["channel"]] = r["score"]
                if r["score"] > best_score[cid]:
                    merged["memory"] = r["memory"]
                    best_score[cid] = r["score"]

    return sorted(
        accumulator.values(),
        key=lambda x: max(x["channel_scores"].values()),
        reverse=True,
    )


def _post_filter_acl(results: list[dict], access_filter) -> list[dict]:
    """Post-filter results by access_groups when Qdrant pre-filter wasn't applied.

    Used for scroll-based methods (search_by_date, search_by_status, etc.)
    which don't accept filter_conditions.
    """
    if not access_filter or not results:
        return results
    allowed_groups: set = set()
    allow_empty = False
    if access_filter.should:
        for cond in access_filter.should:
            if hasattr(cond, "match") and hasattr(cond.match, "any"):
                allowed_groups.update(cond.match.any)
            if hasattr(cond, "is_empty"):
                allow_empty = True
    elif access_filter.must:
        for cond in access_filter.must:
            if hasattr(cond, "is_empty"):
                allow_empty = True
    filtered = []
    for r in results:
        payload = r.get("payload", r)
        doc_groups = payload.get("access_groups", [])
        if not doc_groups:
            if allow_empty or not allowed_groups:
                filtered.append(r)
        elif allowed_groups & set(doc_groups):
            filtered.append(r)
    return filtered


def _qdrant_hit_to_scored(hit: dict, channel: str = "") -> ScoredResult:
    """Convert a Qdrant store result (flat dict) to ScoredResult."""
    chunk_id = str(hit.get("id", "")) or str(uuid.uuid4())
    return ScoredResult(
        chunk_id=chunk_id,
        doc_label=hit.get("doc_label", ""),
        score=float(hit.get("score", 0.0)),
        memory=hit,
        channel=channel,
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
        return [_qdrant_hit_to_scored(h, channel="dense") for h in hits[:limit]]
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
            hits.extend(_post_filter_acl(
                store.search_by_doc_labels(ctx.extracted_jira_keys), ctx.access_filter,
            ))

        for entity in ctx.extracted_title_entities:
            title_hits = _post_filter_acl(
                store.scroll_by_title(entity, limit=5), ctx.access_filter,
            )
            hits.extend(title_hits)

        seen_ids: set[str] = set()
        results: list[ScoredResult] = []
        for h in hits:
            hid = str(h.get("id", ""))
            if hid in seen_ids:
                continue
            seen_ids.add(hid)
            results.append(_qdrant_hit_to_scored(h, channel="exact"))

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
            date_hits = _post_filter_acl(
                store.search_by_date(ctx.extracted_dates, limit=limit), ctx.access_filter,
            )
            hits.extend(date_hits)

        # Person-specific: search by assignee for each resolved name (skips general status)
        if ctx.detected_person:
            for name in ctx.detected_person:
                assignee_hits = _post_filter_acl(
                    store.search_by_assignee(name, limit=limit), ctx.access_filter,
                )
                hits.extend(assignee_hits)
        elif ctx.is_activity_query:
            for status in _ACTIVITY_STATUSES:
                status_hits = _post_filter_acl(
                    store.search_by_status(status, limit=limit), ctx.access_filter,
                )
                hits.extend(status_hits)

        seen_ids: set[str] = set()
        results: list[ScoredResult] = []
        for h in hits:
            hid = str(h.get("id", ""))
            if hid in seen_ids:
                continue
            seen_ids.add(hid)
            results.append(_qdrant_hit_to_scored(h, channel="metadata"))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    except Exception:
        logger.error("recall_metadata failed", workspace=ctx.workspace_id, exc_info=True)
        return []


_MAX_FRONTIER = 50  # Cap BFS frontier to prevent explosion on highly-connected entities


def recall_graph(ctx: RecallContext) -> list[ScoredResult]:
    """Graph channel: find related documents via entity graph traversal.

    Collects seed entities from 4 sources (Jira keys, title entities,
    person names, graph entity match), then expands via iterative BFS
    hop expansion using graph relationships.
    """
    limit = ctx.settings.recall_top_n_graph if ctx.settings else 5
    max_depth = ctx.settings.recall_graph_max_depth if ctx.settings else 2
    try:
        # 1. Collect seed entity names from RecallContext
        seeds: set[str] = set()
        seeds.update(ctx.extracted_jira_keys)
        seeds.update(ctx.extracted_title_entities)
        seeds.update(ctx.detected_person)

        # 2. Graph entity match on query (existing behavior)
        query_for_ner = ctx.translated_query or ctx.original_query
        graph_ents = get_graph_entities([query_for_ner], workspace_id=ctx.workspace_id)
        seeds.update(e["name"] for e in graph_ents if "name" in e)

        if not seeds:
            return []

        # 3. Get direct doc_labels for seeds
        direct = get_doc_labels_by_entities(list(seeds), workspace_id=ctx.workspace_id)
        all_labels: set[str] = {r["doc_label"] for r in direct if "doc_label" in r}

        # 4. Iterative BFS hop expansion
        # NOTE: get_graph_relationships accepts max_depth but does NOT do multi-hop
        # internally. We always pass max_depth=1 and iterate ourselves.
        seen_entities = set(seeds)
        frontier = set(seeds)
        for _hop in range(max_depth):
            if not frontier:
                break
            rels = get_graph_relationships(
                list(frontier)[:_MAX_FRONTIER],
                workspace_id=ctx.workspace_id,
                max_depth=1,
            )
            neighbor_names = {r["source"] for r in rels} | {r["target"] for r in rels}
            frontier = neighbor_names - seen_entities
            seen_entities.update(frontier)
            if frontier:
                expanded = get_doc_labels_by_entities(
                    list(frontier)[:_MAX_FRONTIER],
                    workspace_id=ctx.workspace_id,
                )
                all_labels.update(r["doc_label"] for r in expanded if "doc_label" in r)

        if not all_labels:
            return []

        # 5. Fetch chunks, apply ACL, limit
        store = get_hybrid_store(ctx.workspace_id)
        hits = _post_filter_acl(
            store.search_by_doc_labels(list(all_labels), limit=limit),
            ctx.access_filter,
        )
        return [_qdrant_hit_to_scored(h, channel="graph") for h in hits[:limit]]
    except Exception:
        logger.error("recall_graph failed", workspace=ctx.workspace_id, exc_info=True)
        return []
