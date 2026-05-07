"""Agent memory health metrics (MTRNIX-277).

Pure read-only observability. Talks only to MemoryPostgresStore;
Qdrant / Neo4j / Redis are intentionally not consulted. UI lands in W9,
governance/auto-archive in Phase 4.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import LifecycleStatus
from metatron.ingestion.dedup import hamming_distance

if TYPE_CHECKING:
    from metatron.core.config import Settings
    from metatron.storage.memory_postgres import MemoryPostgresStore

logger = structlog.get_logger(__name__)

_DUP_HARDCAP = 5000


@dataclass(frozen=True)
class GrowthBucket:
    """One day's record-creation count."""

    day: date
    created_count: int


@dataclass(frozen=True)
class AgentMemoryHealth:
    """Point-in-time health snapshot for an agent's memory."""

    agent_id: str
    total_records: int
    total_archived: int
    growth_rate_per_day: float
    growth_timeseries: list[GrowthBucket]
    unused_records: int
    unused_threshold_days: int
    duplicate_ratio: float
    duplicate_clusters_count: int
    duplicate_hamming_threshold: int
    source_distribution: dict[str, int]
    computed_at: datetime
    # Disambiguates "no duplicates found" from "skipped because too large".
    # When True, the dashboard should render "skipped — over Nk active records"
    # instead of a misleading 0% duplicate badge.
    duplicate_detection_skipped: bool = False
    # Population over which the dup compute would have run (ACTIVE count when
    # detection ran; same value when skipped — useful for the dashboard label).
    duplicate_active_population: int = 0


class MemoryHealthService:
    """Compute per-agent memory health on demand. No cache; recompute each call."""

    def __init__(
        self,
        pg_store: MemoryPostgresStore,
        *,
        workspace_id: str,
        settings: Settings,
    ) -> None:
        self._pg = pg_store
        self._workspace_id = workspace_id
        self._settings = settings

    async def compute(self, agent_id: str) -> AgentMemoryHealth:
        """Compute a full health snapshot for the given agent.

        All independent aggregation queries are dispatched in parallel via
        ``asyncio.gather`` to avoid serialising 6+ pool acquisitions on a
        single observability request (the W9 polling dashboard would otherwise
        hit P1 latency under concurrent viewers).
        """
        ws = self._workspace_id
        stale_days = self._settings.memory_stale_after_days
        dup_threshold = self._settings.memory_duplicate_hamming_threshold

        # Six independent aggregations — fanned out concurrently.
        (
            total,
            total_archived,
            unused,
            source_dist_raw,
            recent,
            raw_buckets,
        ) = await asyncio.gather(
            self._pg.count_by_status(ws, agent_id, [LifecycleStatus.ACTIVE]),
            self._pg.count_by_status(
                ws,
                agent_id,
                [LifecycleStatus.ARCHIVED, LifecycleStatus.SUPERSEDED],
            ),
            self._pg.count_unused(
                ws,
                agent_id,
                days=stale_days,
                statuses=[LifecycleStatus.ACTIVE],
            ),
            self._pg.source_distribution_active(ws, agent_id),
            self._pg.count_created_since_active(ws, agent_id, days=7),
            self._pg.growth_timeseries_active(ws, agent_id, days=30),
        )
        source_dist = {k: v for k, v in source_dist_raw.items() if v > 0}
        growth_rate_per_day = recent / 7.0
        growth_ts = self._zero_fill_days(raw_buckets, days=30)

        dup_skipped = False
        if total == 0:
            dup_ratio, dup_clusters = 0.0, 0
        elif total > _DUP_HARDCAP:
            logger.warning(
                "memory_health.dup_skipped_size_cap",
                workspace_id=ws,
                agent_id=agent_id,
                total_active=total,
                cap=_DUP_HARDCAP,
            )
            dup_ratio, dup_clusters = 0.0, 0
            dup_skipped = True
        else:
            dup_ratio, dup_clusters = await self._compute_duplicates(
                ws,
                agent_id,
                dup_threshold,
                total,
            )

        return AgentMemoryHealth(
            agent_id=agent_id,
            total_records=total,
            total_archived=total_archived,
            growth_rate_per_day=growth_rate_per_day,
            growth_timeseries=growth_ts,
            unused_records=unused,
            unused_threshold_days=stale_days,
            duplicate_ratio=dup_ratio,
            duplicate_clusters_count=dup_clusters,
            duplicate_hamming_threshold=dup_threshold,
            source_distribution=source_dist,
            computed_at=datetime.now(UTC),
            duplicate_detection_skipped=dup_skipped,
            duplicate_active_population=total,
        )

    async def _compute_duplicates(
        self,
        workspace_id: str,
        agent_id: str,
        threshold: int,
        total_active: int,
    ) -> tuple[float, int]:
        # Two independent reads — fan out. A record created/updated between
        # these two queries can show up in one but not the other, slightly
        # skewing null_count. Acceptable for an observability snapshot — the
        # next /health call self-corrects.
        rows, null_count = await asyncio.gather(
            self._pg.list_simhashes_active(workspace_id, agent_id),
            self._pg.count_active_with_null_simhash(workspace_id, agent_id),
        )

        if null_count:
            logger.warning(
                "memory_health.simhash_null_skipped",
                workspace_id=workspace_id,
                agent_id=agent_id,
                null_count=null_count,
            )

        # Defensive guard: simhash == 0 means "not computed" (empty/whitespace content).
        sims: list[tuple[str, int]] = [(rid, s) for rid, s in rows if s]
        if len(sims) < 2:
            return (0.0, 0)

        # O(N^2) hamming compare + union-find — pure CPU work that would block
        # the event loop for ~10s at the _DUP_HARDCAP=5000 ceiling. Off-thread
        # so the loop stays responsive for other observability calls.
        return await asyncio.to_thread(
            self._cluster_duplicates_sync, sims, threshold, total_active
        )

    @staticmethod
    def _cluster_duplicates_sync(
        sims: list[tuple[str, int]],
        threshold: int,
        total_active: int,
    ) -> tuple[float, int]:
        """Pure-CPU clustering helper — runs in a worker thread."""
        n = len(sims)
        parent: dict[str, str] = {rid: rid for rid, _ in sims}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(n):
            for j in range(i + 1, n):
                if hamming_distance(sims[i][1], sims[j][1]) <= threshold:
                    union(sims[i][0], sims[j][0])

        clusters: dict[str, list[str]] = {}
        for rid, _ in sims:
            clusters.setdefault(find(rid), []).append(rid)

        multi = [c for c in clusters.values() if len(c) >= 2]
        in_clusters = sum(len(c) for c in multi)
        ratio = in_clusters / total_active if total_active else 0.0
        return (ratio, len(multi))

    @staticmethod
    def _zero_fill_days(
        raw: list[tuple[date, int]],
        *,
        days: int,
    ) -> list[GrowthBucket]:
        today = datetime.now(UTC).date()
        counts = {d: c for d, c in raw}
        out: list[GrowthBucket] = []
        for offset in range(days - 1, -1, -1):
            d = today - timedelta(days=offset)
            out.append(GrowthBucket(day=d, created_count=counts.get(d, 0)))
        return out
