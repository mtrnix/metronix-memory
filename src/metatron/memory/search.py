"""Hybrid memory search — blends Qdrant, Neo4j, and Redis legs.

L3 service layer. Fans out three parallel legs, hydrates records, applies tag
post-filter, normalizes qdrant scores, and blends into a single ranking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

import structlog

from metatron.core.config import get_settings
from metatron.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
)
from metatron.memory.serde import record_from_qdrant_payload
from metatron.storage.memory_graph import get_agent_memories

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable

    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.memory_redis import RedisSessionCache

logger = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class MemorySearchWeights:
    dense: float = 0.6
    graph: float = 0.3
    session: float = 0.1
    top_k_multiplier: int = 3


def _default_weights() -> MemorySearchWeights:
    s = get_settings()
    return MemorySearchWeights(
        dense=s.memory_search_dense_weight,
        graph=s.memory_search_graph_weight,
        session=s.memory_search_session_weight,
        top_k_multiplier=s.memory_search_top_k_multiplier,
    )


async def _safe_gather_leg(
    coro: Awaitable[T],
    *,
    default: T,
    leg: str,
) -> T:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — log and return default
        logger.warning("memory_search.leg_failed", leg=leg, error=str(exc))
        return default


class MemorySearchService:
    """Hybrid search across memory stores with weighted blend.

    Qdrant leg provides dense+sparse hits with content.
    Neo4j leg (agent-scoped) returns metadata for graph-pinned memories.
    Redis leg (session-scoped) adds recent in-session records via substring match.
    """

    def __init__(
        self,
        qdrant: MemoryQdrantStore,
        redis: RedisSessionCache | None = None,
        *,
        weights: MemorySearchWeights | None = None,
        pg_store: MemoryPostgresStore | None = None,
    ) -> None:
        self._qdrant = qdrant
        self._redis = redis
        self._weights = weights if weights is not None else _default_weights()
        # ``pg_store`` is used by the graph-leg status post-filter (MTRNIX-314).
        # Legacy construction paths (no pg_store) keep working — graph-leg
        # status filtering is skipped, matching pre-ticket behaviour.
        self._pg_store = pg_store

    async def hybrid_search(
        self,
        workspace_id: str,
        query: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        top_k: int = 5,
        status_filter: list[LifecycleStatus] | None = None,
    ) -> list[MemorySearchResult]:
        weights = self._weights
        pool = max(1, top_k * weights.top_k_multiplier)
        scope_value = scope.value if scope is not None else None
        status_exclude = _compute_exclude_set(status_filter)

        qdrant_default: list[dict[str, Any]] = []
        qdrant_coro: Awaitable[list[dict[str, Any]]] = _safe_gather_leg(
            self._qdrant.search(
                query,
                agent_id=agent_id,
                scope=scope_value,
                top_k=pool,
                status_exclude=status_exclude,
            ),
            default=qdrant_default,
            leg="qdrant",
        )

        graph_default: list[dict[str, Any]] = []
        if agent_id is not None:
            graph_coro: Awaitable[list[dict[str, Any]]] = _safe_gather_leg(
                asyncio.to_thread(
                    get_agent_memories,
                    workspace_id,
                    agent_id,
                    scope_value,
                    pool,
                ),
                default=graph_default,
                leg="graph",
            )
        else:
            graph_coro = _noop_list()

        session_default: list[MemoryRecord] = []
        if self._redis is not None and session_id is not None:
            session_coro: Awaitable[list[MemoryRecord]] = _safe_gather_leg(
                self._redis.list(workspace_id, session_id),
                default=session_default,
                leg="session",
            )
        else:
            session_coro = _noop_list()

        qdrant_hits, graph_hits, session_hits = await asyncio.gather(
            qdrant_coro,
            graph_coro,
            session_coro,
        )

        session_query = query.lower()
        session_matches: list[MemoryRecord] = [
            rec for rec in session_hits if session_query in (rec.content or "").lower()
        ]
        session_lookup: dict[str, MemoryRecord] = {r.id: r for r in session_hits}

        merged: dict[str, MemorySearchResult] = {}
        raw_dense: dict[str, float] = {}
        in_session: dict[str, bool] = {}

        for hit in qdrant_hits:
            record = record_from_qdrant_payload(hit, workspace_id)
            raw_dense[record.id] = float(hit.get("score", 0.0) or 0.0)
            merged[record.id] = MemorySearchResult(
                record=record,
                dense_score=0.0,
                sparse_score=0.0,
                graph_score=0.0,
            )

        for node in graph_hits:
            record_id = node.get("id")
            if not record_id:
                continue
            importance = float(node.get("importance_score", 0.0) or 0.0)
            if record_id in merged:
                merged[record_id].graph_score = importance
                continue
            hydrated = _hydrate_graph_record(node, workspace_id, session_lookup)
            if hydrated is None:
                continue
            merged[record_id] = MemorySearchResult(
                record=hydrated,
                dense_score=0.0,
                sparse_score=0.0,
                graph_score=importance,
            )

        for record in session_matches:
            in_session[record.id] = True
            if record.id in merged:
                continue
            merged[record.id] = MemorySearchResult(
                record=record,
                dense_score=0.0,
                sparse_score=0.0,
                graph_score=0.0,
            )

        # MTRNIX-314: graph-leg status post-filter.
        # Graph-only hits (no Qdrant peer, not in session cache) carry no
        # ``status`` payload, so Qdrant's exclude filter can't see them.
        # Fan them out into a batched PG lookup and drop any record whose
        # status is outside the include-set.
        if status_filter is not None and self._pg_store is not None:
            allowed_statuses = {s.value for s in status_filter}
            graph_only_ids = [
                rid for rid in merged if rid not in raw_dense and rid not in session_lookup
            ]
            if graph_only_ids:
                statuses = await self._pg_store.get_many_statuses(workspace_id, graph_only_ids)
                for rid in graph_only_ids:
                    # Missing row -> treat as ACTIVE (safe default; matches
                    # Qdrant exclude semantics).
                    status_val = statuses.get(rid, LifecycleStatus.ACTIVE).value
                    if status_val not in allowed_statuses:
                        merged.pop(rid, None)
                        raw_dense.pop(rid, None)

        if tags:
            tag_set = set(tags)
            merged = {rid: r for rid, r in merged.items() if tag_set.intersection(r.record.tags)}
            raw_dense = {rid: v for rid, v in raw_dense.items() if rid in merged}

        norm_dense = _min_max_normalize(raw_dense, merged.keys())

        for rid, result in merged.items():
            nd = norm_dense.get(rid, 0.0)
            result.dense_score = nd
            boost = 1.0 if in_session.get(rid, False) else 0.0
            result.score = (
                weights.dense * nd + weights.graph * result.graph_score + weights.session * boost
            )

        ranked = sorted(merged.values(), key=lambda r: r.score, reverse=True)[:top_k]
        for i, r in enumerate(ranked):
            r.rank = i + 1

        logger.debug(
            "memory_search.completed",
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            qdrant_hits=len(qdrant_hits),
            graph_hits=len(graph_hits),
            session_matches=len(session_matches),
            returned=len(ranked),
        )
        return ranked


async def _noop_list() -> list[Any]:
    return []


def _hydrate_graph_record(
    node: dict[str, Any],
    workspace_id: str,
    session_lookup: dict[str, MemoryRecord],
) -> MemoryRecord | None:
    record_id = str(node.get("id") or "")
    if not record_id:
        return None

    cached = session_lookup.get(record_id)
    content = cached.content if cached is not None else ""
    if not content:
        return None

    scope_raw = node.get("scope") or MemoryScope.PER_AGENT.value
    try:
        scope = MemoryScope(scope_raw)
    except ValueError:
        scope = MemoryScope.PER_AGENT

    tags = node.get("tags") or (cached.tags if cached else [])
    return MemoryRecord(
        id=record_id,
        workspace_id=str(node.get("workspace_id") or workspace_id),
        agent_id=str(node.get("agent_id") or ""),
        scope=scope,
        source_type=str(node.get("source_type") or ""),
        content=content,
        tags=list(tags),
        importance_score=float(node.get("importance_score") or 0.0),
    )


def _compute_exclude_set(
    status_filter: list[LifecycleStatus] | None,
) -> list[str] | None:
    """Convert an include-set of statuses to an exclude-set for Qdrant.

    MTRNIX-314. Returns ``None`` when ``status_filter`` is None (filter
    disabled). Otherwise returns every ``LifecycleStatus`` value that is NOT
    in the include-set so the Qdrant ``must_not`` filter rejects them.
    """
    if status_filter is None:
        return None
    include = {s.value for s in status_filter}
    return [s.value for s in LifecycleStatus if s.value not in include]


def _min_max_normalize(
    raw: dict[str, float],
    all_ids: Iterable[str],
) -> dict[str, float]:
    ids = list(all_ids)
    if not raw:
        return dict.fromkeys(ids, 0.0)
    values = list(raw.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {rid: (1.0 if rid in raw else 0.0) for rid in ids}
    span = hi - lo
    return {rid: ((raw[rid] - lo) / span if rid in raw else 0.0) for rid in ids}
