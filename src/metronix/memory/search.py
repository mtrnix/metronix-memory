"""Hybrid memory search — blends Qdrant, Neo4j, and Redis legs.

L3 service layer. Fans out three parallel legs, hydrates records, applies tag
post-filter, normalizes qdrant scores, and blends into a single ranking.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from metronix.core.config import get_settings
from metronix.core.models import (
    GraphHydrationHealth,
    GraphHydrationStatus,
    GraphSearchLegHealth,
    LifecycleStatus,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchOutcome,
    MemorySearchResult,
    SearchFailureReason,
    SearchLegHealth,
    SearchLegsHealth,
    SearchLegStatus,
)
from metronix.memory.serde import record_from_qdrant_payload
from metronix.storage.memory_graph import get_agent_memories

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable

    from metronix.storage.memory_postgres import MemoryPostgresStore
    from metronix.storage.memory_qdrant import MemoryQdrantStore
    from metronix.storage.memory_redis import RedisSessionCache

logger = structlog.get_logger(__name__)


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


@dataclass(frozen=True)
class _LegOutcome[T]:
    value: T
    health: SearchLegHealth


async def _safe_gather_leg[T](
    coro: Awaitable[T],
    *,
    default: T,
    leg: str,
) -> _LegOutcome[T]:
    try:
        value = await coro
    except Exception as exc:  # noqa: BLE001 — preserve useful surviving legs
        logger.warning("memory_search.leg_failed", leg=leg, error=str(exc))
        timeout = isinstance(exc, TimeoutError)
        return _LegOutcome(
            default,
            SearchLegHealth(
                SearchLegStatus.FAILED,
                SearchFailureReason.TIMEOUT if timeout else SearchFailureReason.BACKEND_ERROR,
                True if timeout else None,
            ),
        )
    return _LegOutcome(value, SearchLegHealth(SearchLegStatus.OK, None, None))


async def _skipped_leg[T](default: T) -> _LegOutcome[T]:
    return _LegOutcome(default, SearchLegHealth(SearchLegStatus.SKIPPED, None, None))


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
        # Strong references to in-flight fire-and-forget tasks (MTRNIX-277).
        # asyncio only keeps weak refs to tasks created via create_task — without
        # this set the GC could reap a pending touch task mid-await and Python
        # would log "Task was destroyed but it is pending!" silently. The
        # done-callback removes finished tasks so the set never grows unbounded.
        self._touch_tasks: set[asyncio.Task[None]] = set()

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
        kind_filter: list[MemoryKind] | None = None,
    ) -> list[MemorySearchResult]:
        """Return ranked records; use hybrid_search_detailed for search health."""
        outcome = await self.hybrid_search_detailed(
            workspace_id,
            query,
            agent_id=agent_id,
            scope=scope,
            tags=tags,
            session_id=session_id,
            top_k=top_k,
            status_filter=status_filter,
            kind_filter=kind_filter,
        )
        return outcome.results

    async def hybrid_search_detailed(
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
        kind_filter: list[MemoryKind] | None = None,
    ) -> MemorySearchOutcome:
        """Return ranked records and explicit retrieval/hydration diagnostics."""
        if not query.strip():
            raise ValueError("query must not be blank")
        weights = self._weights
        pool = max(1, top_k * weights.top_k_multiplier)
        scope_value = scope.value if scope is not None else None
        status_exclude = _compute_exclude_set(status_filter)
        kind_values = [k.value for k in kind_filter] if kind_filter is not None else None

        qdrant_default: list[dict[str, Any]] = []
        qdrant_coro: Awaitable[_LegOutcome[list[dict[str, Any]]]] = _safe_gather_leg(
            self._qdrant.search(
                query,
                agent_id=agent_id,
                scope=scope_value,
                top_k=pool,
                status_exclude=status_exclude,
                kind_filter=kind_values,
            ),
            default=qdrant_default,
            leg="qdrant",
        )

        graph_default: list[dict[str, Any]] = []
        if agent_id is not None:
            graph_coro: Awaitable[_LegOutcome[list[dict[str, Any]]]] = _safe_gather_leg(
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
            graph_coro = _skipped_leg(graph_default)

        session_default: list[MemoryRecord] = []
        if self._redis is not None and session_id is not None:
            session_coro: Awaitable[_LegOutcome[list[MemoryRecord]]] = _safe_gather_leg(
                self._redis.list(workspace_id, session_id),
                default=session_default,
                leg="session",
            )
        else:
            session_coro = _skipped_leg(session_default)

        qdrant_leg, graph_leg, session_leg = await asyncio.gather(
            qdrant_coro,
            graph_coro,
            session_coro,
        )

        qdrant_hits = qdrant_leg.value
        graph_hits = graph_leg.value

        def eligible(record: MemoryRecord) -> bool:
            return (
                record.workspace_id == workspace_id
                and (agent_id is None or record.agent_id == agent_id)
                and (scope is None or record.scope == scope)
                and (not kind_filter or record.kind in kind_filter)
            )

        # The Redis key partitions by workspace/session, not by agent or kind.
        # Filter before building either substring hits or graph hydration lookup.
        session_hits = [record for record in session_leg.value if eligible(record)]
        resolved = unavailable = invalid = 0

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
                invalid += 1
                continue
            importance = float(node.get("importance_score", 0.0) or 0.0)
            if record_id in merged:
                merged[record_id].graph_score = importance
                resolved += 1
                continue
            hydrated = _hydrate_graph_record(node, workspace_id, session_lookup)
            if hydrated is None:
                unavailable += 1
                continue
            resolved += 1
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

        # Fire-and-forget: update last_accessed_at for returned records (MTRNIX-277).
        if ranked and agent_id is not None and self._pg_store is not None:
            record_ids = [r.record.id for r in ranked]
            with contextlib.suppress(RuntimeError):
                # RuntimeError is raised when there is no running event loop
                # (e.g. in some test environments). Suppress to keep behaviour safe.
                task = asyncio.create_task(
                    self._safe_bulk_touch(workspace_id, agent_id, record_ids)
                )
                self._touch_tasks.add(task)
                task.add_done_callback(self._touch_tasks.discard)

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
        if graph_leg.health.status != SearchLegStatus.OK:
            hydration_status = GraphHydrationStatus.NOT_ATTEMPTED
        elif unavailable or invalid:
            hydration_status = (
                GraphHydrationStatus.PARTIAL if resolved else GraphHydrationStatus.UNAVAILABLE
            )
        else:
            hydration_status = GraphHydrationStatus.OK
        legs = SearchLegsHealth(
            qdrant=qdrant_leg.health,
            graph=GraphSearchLegHealth(
                status=graph_leg.health.status,
                reason=graph_leg.health.reason,
                retryable=graph_leg.health.retryable,
                hydration=GraphHydrationHealth(
                    hydration_status,
                    len(graph_hits),
                    resolved,
                    unavailable,
                    invalid,
                ),
            ),
            session=session_leg.health,
        )
        # Hydration misses can occur on healthy searches: graph candidates are
        # query-independent and may be absent from both content sources.
        partial = any(
            leg.status == SearchLegStatus.FAILED for leg in (legs.qdrant, legs.graph, legs.session)
        )
        return MemorySearchOutcome(results=ranked, partial=partial, legs=legs)

    async def _safe_bulk_touch(
        self,
        workspace_id: str,
        agent_id: str,
        record_ids: list[str],
    ) -> None:
        """Fire-and-forget update of last_accessed_at; never raises."""
        try:
            await self._pg_store.bulk_touch_last_accessed(  # type: ignore[union-attr]
                workspace_id,
                agent_id,
                record_ids,
            )
        except Exception:
            logger.warning(
                "memory_search.touch_failed",
                workspace_id=workspace_id,
                agent_id=agent_id,
                count=len(record_ids),
                exc_info=True,
            )


def _hydrate_graph_record(
    node: dict[str, Any],
    workspace_id: str,
    session_lookup: dict[str, MemoryRecord],
) -> MemoryRecord | None:
    record_id = str(node.get("id") or "")
    if not record_id:
        return None

    cached = session_lookup.get(record_id)
    if cached is None or cached.workspace_id != workspace_id or not cached.content:
        return None
    # Cache records carry the content's ownership, kind, and lifecycle metadata.
    # Rebuilding from graph metadata would reset omitted fields (e.g. kind=FACT).
    return cached


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
