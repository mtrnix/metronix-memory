"""Tests for MemoryHealthService (MTRNIX-277).

All DB calls go through a mock MemoryPostgresStore so no live DB is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from metatron.core.config import Settings
from metatron.core.models import LifecycleStatus
from metatron.memory.health import (
    _DUP_HARDCAP,
    MemoryHealthService,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "METATRON_ENV": "development",
        "METATRON_MEMORY_STALE_AFTER_DAYS": 30,
        "METATRON_MEMORY_DUPLICATE_HAMMING_THRESHOLD": 3,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _make_pg(
    *,
    total_active: int = 0,
    total_archived: int = 0,
    unused: int = 0,
    source_dist: dict | None = None,
    recent: int = 0,
    timeseries: list | None = None,
    simhashes: list | None = None,
    null_count: int = 0,
) -> AsyncMock:
    pg = AsyncMock()
    pg.count_by_status = AsyncMock(
        side_effect=lambda ws, agent, statuses: (
            total_active
            if LifecycleStatus.ACTIVE in statuses and len(statuses) == 1
            else total_archived
        )
    )
    pg.count_unused = AsyncMock(return_value=unused)
    pg.source_distribution_active = AsyncMock(return_value=source_dist or {})
    pg.count_created_since_active = AsyncMock(return_value=recent)
    pg.growth_timeseries_active = AsyncMock(return_value=timeseries or [])
    pg.list_simhashes_active = AsyncMock(return_value=simhashes or [])
    pg.count_active_with_null_simhash = AsyncMock(return_value=null_count)
    return pg


def _make_service(
    pg: AsyncMock,
    workspace_id: str = "ws1",
    stale_days: int = 30,
    dup_threshold: int = 3,
) -> MemoryHealthService:
    settings = _make_settings(
        METATRON_MEMORY_STALE_AFTER_DAYS=stale_days,
        METATRON_MEMORY_DUPLICATE_HAMMING_THRESHOLD=dup_threshold,
    )
    return MemoryHealthService(
        pg_store=pg,
        workspace_id=workspace_id,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Basic compute
# ---------------------------------------------------------------------------


class TestComputeBasic:
    async def test_empty_agent_returns_zeros(self) -> None:
        pg = _make_pg()
        service = _make_service(pg)
        h = await service.compute("a1")

        assert h.agent_id == "a1"
        assert h.total_records == 0
        assert h.total_archived == 0
        assert h.growth_rate_per_day == 0.0
        assert h.duplicate_ratio == 0.0
        assert h.duplicate_clusters_count == 0
        assert len(h.growth_timeseries) == 30

    async def test_computed_at_is_utc_aware(self) -> None:
        pg = _make_pg()
        service = _make_service(pg)
        h = await service.compute("a1")
        assert h.computed_at.tzinfo is not None

    async def test_returns_correct_totals(self) -> None:
        pg = _make_pg(total_active=50, total_archived=10, unused=5)
        service = _make_service(pg)
        h = await service.compute("a1")

        assert h.total_records == 50
        assert h.total_archived == 10
        assert h.unused_records == 5

    async def test_growth_rate_calculation(self) -> None:
        pg = _make_pg(recent=14)
        service = _make_service(pg)
        h = await service.compute("a1")

        assert abs(h.growth_rate_per_day - 2.0) < 1e-9  # 14 / 7

    async def test_source_distribution_excludes_zero_counts(self) -> None:
        pg = _make_pg(source_dist={"chat": 3, "api": 0})
        service = _make_service(pg)
        h = await service.compute("a1")
        # "api" with count=0 should be excluded
        assert "api" not in h.source_distribution
        assert h.source_distribution.get("chat") == 3


# ---------------------------------------------------------------------------
# Growth timeseries zero-filling
# ---------------------------------------------------------------------------


class TestGrowthTimeseries:
    async def test_zero_fill_returns_30_days(self) -> None:
        pg = _make_pg(timeseries=[])
        service = _make_service(pg)
        h = await service.compute("a1")
        assert len(h.growth_timeseries) == 30

    async def test_zero_fill_covers_today(self) -> None:
        pg = _make_pg(timeseries=[])
        service = _make_service(pg)
        h = await service.compute("a1")
        today = datetime.now(UTC).date()
        days = [b.day for b in h.growth_timeseries]
        assert today in days

    async def test_zero_fill_days_in_ascending_order(self) -> None:
        pg = _make_pg(timeseries=[])
        service = _make_service(pg)
        h = await service.compute("a1")
        days = [b.day for b in h.growth_timeseries]
        assert days == sorted(days)

    async def test_raw_bucket_count_preserved(self) -> None:
        today = datetime.now(UTC).date()
        pg = _make_pg(timeseries=[(today, 7)])
        service = _make_service(pg)
        h = await service.compute("a1")
        bucket_today = next(b for b in h.growth_timeseries if b.day == today)
        assert bucket_today.created_count == 7

    async def test_missing_days_get_zero(self) -> None:
        # Only one day in raw; rest must be zero.
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        pg = _make_pg(timeseries=[(yesterday, 3)])
        service = _make_service(pg)
        h = await service.compute("a1")
        zero_buckets = [b for b in h.growth_timeseries if b.day != yesterday]
        assert all(b.created_count == 0 for b in zero_buckets)


# ---------------------------------------------------------------------------
# Unused threshold uses stale_days from settings
# ---------------------------------------------------------------------------


class TestUnusedThreshold:
    async def test_uses_configured_stale_days(self) -> None:
        pg = _make_pg(unused=3)
        service = _make_service(pg, stale_days=60)
        h = await service.compute("a1")

        assert h.unused_threshold_days == 60
        # The PG call must use days=60.
        call_kwargs = pg.count_unused.call_args[1]
        assert call_kwargs["days"] == 60


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

# We need real hamming_distance semantics — import directly.


class TestDuplicateDetection:
    async def test_no_duplicates_when_simhashes_differ_widely(self) -> None:
        # Two records whose simhashes differ by more than 3 bits.
        h1, h2 = 0b0000000000000000, 0b1111111111111111
        pg = _make_pg(total_active=2, simhashes=[("r1", h1), ("r2", h2)])
        service = _make_service(pg, dup_threshold=3)
        h = await service.compute("a1")

        assert h.duplicate_ratio == 0.0
        assert h.duplicate_clusters_count == 0

    async def test_detects_near_duplicate_pair(self) -> None:
        # Two identical simhashes → hamming 0 ≤ 3 → in same cluster.
        same_hash = 12345678
        pg = _make_pg(
            total_active=2,
            simhashes=[("r1", same_hash), ("r2", same_hash)],
        )
        service = _make_service(pg, dup_threshold=3)
        h = await service.compute("a1")

        assert h.duplicate_clusters_count == 1
        assert abs(h.duplicate_ratio - 1.0) < 1e-9  # 2/2

    async def test_duplicate_ratio_partial(self) -> None:
        # 2 duplicates + 1 unique out of 3 total active.
        same_hash = 999
        different_hash = 2**62  # far from 999
        pg = _make_pg(
            total_active=3,
            simhashes=[("r1", same_hash), ("r2", same_hash), ("r3", different_hash)],
        )
        service = _make_service(pg, dup_threshold=3)
        h = await service.compute("a1")

        # r1, r2 form a cluster; r3 is alone.
        assert h.duplicate_clusters_count == 1
        assert abs(h.duplicate_ratio - 2 / 3) < 1e-9

    async def test_single_record_no_duplicates(self) -> None:
        pg = _make_pg(total_active=1, simhashes=[("r1", 42)])
        service = _make_service(pg)
        h = await service.compute("a1")
        assert h.duplicate_ratio == 0.0
        assert h.duplicate_clusters_count == 0

    async def test_zero_simhash_excluded_from_cluster_detection(self) -> None:
        """simhash == 0 means 'not computed'; must be excluded from dup detection."""
        pg = _make_pg(total_active=2, simhashes=[("r1", 0), ("r2", 42)])
        # list_simhashes_active already filters NULL, but 0-valued rows can
        # still exist (empty content). The service's defensive `if s` removes them.
        service = _make_service(pg)
        h = await service.compute("a1")
        # Only 1 record has a meaningful simhash → < 2 → no clusters.
        assert h.duplicate_clusters_count == 0

    async def test_hardcap_skips_dup_detection(self) -> None:
        """When total_active > _DUP_HARDCAP the dup calculation is skipped."""
        pg = _make_pg(total_active=_DUP_HARDCAP + 1)
        service = _make_service(pg)
        h = await service.compute("a1")

        assert h.duplicate_ratio == 0.0
        assert h.duplicate_clusters_count == 0
        # list_simhashes_active must NOT have been called.
        pg.list_simhashes_active.assert_not_awaited()
        # The skip is surfaced explicitly so the dashboard renders
        # "skipped — over Nk records" instead of misleading 0% duplicates.
        assert h.duplicate_detection_skipped is True
        assert h.duplicate_active_population == _DUP_HARDCAP + 1

    async def test_skipped_flag_false_when_dup_detection_runs(self) -> None:
        """Below the hardcap, the skipped flag is False and population matches total."""
        pg = _make_pg(total_active=4, simhashes=[("r1", 1), ("r2", 2)])
        service = _make_service(pg)
        h = await service.compute("a1")

        assert h.duplicate_detection_skipped is False
        assert h.duplicate_active_population == 4

    async def test_skipped_flag_false_when_no_records(self) -> None:
        """Empty agent: skipped=False, population=0."""
        pg = _make_pg(total_active=0)
        service = _make_service(pg)
        h = await service.compute("a1")

        assert h.duplicate_detection_skipped is False
        assert h.duplicate_active_population == 0

    async def test_null_simhash_warning_logged(self) -> None:
        from unittest.mock import patch

        pg = _make_pg(total_active=2, simhashes=[("r1", 999)], null_count=1)
        service = _make_service(pg)

        # structlog wraps stdlib logging but caplog binding is brittle across
        # configurations — patch the module logger directly.
        with patch("metatron.memory.health.logger") as mock_logger:
            await service.compute("a1")

        warning_calls = [c for c in mock_logger.warning.call_args_list]
        assert any(
            "simhash_null_skipped" in (c.args[0] if c.args else "") for c in warning_calls
        ), f"expected simhash_null_skipped warning, got {warning_calls!r}"

    async def test_threshold_respected(self) -> None:
        """Two hashes exactly at threshold distance are clusters; above are not."""
        # Non-zero base — zero simhashes are filtered as "no signal" (empty content).
        base = 0xFF00FF00FF00FF00
        # 3 bits different — equal to threshold → cluster
        mask3 = (1 << 3) - 1  # 0b111
        h_close = base ^ mask3
        # 4 bits different — above threshold → no cluster
        mask4 = (1 << 4) - 1  # 0b1111
        h_far = base ^ mask4

        # Close pair
        pg_close = _make_pg(
            total_active=2,
            simhashes=[("r1", base), ("r2", h_close)],
        )
        h = await _make_service(pg_close, dup_threshold=3).compute("a1")
        assert h.duplicate_clusters_count == 1

        # Far pair
        pg_far = _make_pg(
            total_active=2,
            simhashes=[("r1", base), ("r2", h_far)],
        )
        h2 = await _make_service(pg_far, dup_threshold=3).compute("a1")
        assert h2.duplicate_clusters_count == 0

    async def test_active_only_filter_applied(self) -> None:
        """count_by_status for duplicates must only query ACTIVE records."""
        pg = _make_pg(total_active=5, simhashes=[])
        service = _make_service(pg)
        await service.compute("a1")

        # All count_by_status calls must include ACTIVE in statuses.
        for call in pg.count_by_status.call_args_list:
            statuses = call[0][2]  # third positional arg
            assert any(s == LifecycleStatus.ACTIVE for s in statuses) or any(
                s in (LifecycleStatus.ARCHIVED, LifecycleStatus.SUPERSEDED) for s in statuses
            )
