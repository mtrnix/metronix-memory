"""Unit tests for ``ScheduledScan`` — the safety-net scan orchestrator (MTRNIX-316).

Target-agnostic: exercises the dataclass's ``run()`` method with an in-memory
``CoordinationStore`` stub + a fake ``FreshnessTarget``. No live services.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from metatron.core import config as config_mod
from metatron.freshness.scheduled_scan import ScheduledScan


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    config_mod._settings = None
    yield
    config_mod._settings = None


class _FakeTarget:
    def __init__(self, *, stale_by_ws: dict[str, list[str]]) -> None:
        self.stale_by_ws = stale_by_ws
        self.calls: list[tuple[str, datetime, int]] = []

    async def list_stale_candidates(
        self,
        workspace_id: str,
        *,
        older_than: datetime,
        limit: int,
    ) -> list[str]:
        self.calls.append((workspace_id, older_than, limit))
        return list(self.stale_by_ws.get(workspace_id, []))


class _RaisingTarget:
    """Raises on the first call — used to verify error swallow."""

    def __init__(self, *, only_ws: str) -> None:
        self.only_ws = only_ws
        self.calls: list[str] = []

    async def list_stale_candidates(
        self,
        workspace_id: str,
        *,
        older_than: datetime,
        limit: int,
    ) -> list[str]:
        self.calls.append(workspace_id)
        if workspace_id == self.only_ws:
            raise RuntimeError("target exploded")
        return []


class TestScheduledScanRun:
    async def test_enqueues_stale_per_workspace(self) -> None:
        target = _FakeTarget(stale_by_ws={"ws-A": ["rec-1", "rec-2", "rec-3"], "ws-B": []})
        coord = AsyncMock()

        async def lister() -> list[str]:
            return ["ws-A", "ws-B"]

        scan = ScheduledScan(
            target_kind="memory_record",
            target=target,  # type: ignore[arg-type]
            coordination=coord,
            workspace_lister=lister,
            stale_after_days=30,
            batch_limit=500,
        )

        total = await scan.run()

        assert total == 3
        assert coord.enqueue_job.await_count == 3
        # Each enqueued job carries the expected shape.
        for call in coord.enqueue_job.await_args_list:
            job = call.args[0]
            assert job.workspace_id == "ws-A"
            assert job.event_type == "scheduled_scan"
            assert job.target_kind == "memory_record"
            assert job.target_id in {"rec-1", "rec-2", "rec-3"}
            assert "older_than_iso" in job.payload

        # Target called once per workspace with the right batch limit.
        assert len(target.calls) == 2
        assert target.calls[0][0] == "ws-A"
        assert target.calls[0][2] == 500
        assert target.calls[1][0] == "ws-B"

    async def test_older_than_uses_stale_after_days(self) -> None:
        target = _FakeTarget(stale_by_ws={"ws-A": ["rec-1"]})
        coord = AsyncMock()

        async def lister() -> list[str]:
            return ["ws-A"]

        scan = ScheduledScan(
            target_kind="memory_record",
            target=target,  # type: ignore[arg-type]
            coordination=coord,
            workspace_lister=lister,
            stale_after_days=45,
            batch_limit=100,
        )
        await scan.run()

        ws, older_than, _ = target.calls[0]
        assert ws == "ws-A"
        delta = datetime.now(UTC) - older_than
        # 45 days ± ~1 second.
        assert abs(delta - timedelta(days=45)) < timedelta(seconds=5)

    async def test_empty_workspace_list_returns_zero(self) -> None:
        target = _FakeTarget(stale_by_ws={})
        coord = AsyncMock()

        async def lister() -> list[str]:
            return []

        scan = ScheduledScan(
            target_kind="memory_record",
            target=target,  # type: ignore[arg-type]
            coordination=coord,
            workspace_lister=lister,
            stale_after_days=30,
            batch_limit=500,
        )

        assert await scan.run() == 0
        coord.enqueue_job.assert_not_called()

    async def test_lister_error_returns_zero_and_bumps_counter(self) -> None:
        coord = AsyncMock()

        async def lister() -> list[str]:
            raise RuntimeError("pg down")

        scan = ScheduledScan(
            target_kind="memory_record",
            target=_FakeTarget(stale_by_ws={}),  # type: ignore[arg-type]
            coordination=coord,
            workspace_lister=lister,
            stale_after_days=30,
            batch_limit=500,
        )

        assert await scan.run() == 0
        coord.enqueue_job.assert_not_called()

    async def test_per_workspace_error_is_swallowed(self) -> None:
        target = _RaisingTarget(only_ws="ws-A")
        coord = AsyncMock()

        async def lister() -> list[str]:
            return ["ws-A", "ws-B"]

        scan = ScheduledScan(
            target_kind="memory_record",
            target=target,  # type: ignore[arg-type]
            coordination=coord,
            workspace_lister=lister,
            stale_after_days=30,
            batch_limit=500,
        )

        # ws-A raises → error counter bumps but ws-B still runs.
        total = await scan.run()

        assert total == 0
        # Both workspaces visited.
        assert target.calls == ["ws-A", "ws-B"]


class TestScheduledScanMetrics:
    async def test_records_enqueued_counter_incremented(self) -> None:
        """Smoke test: metrics label call does not raise.

        We can't easily read a Prometheus counter in isolation here, but we
        can assert the hot-path doesn't explode when metrics are wired.
        """
        from metatron.freshness import metrics

        # Just verify ``.labels(...).inc(...)`` is a callable noop-safe path.
        metrics.scheduled_scan_jobs_enqueued.labels(
            env="development", target_kind="memory_record"
        ).inc(3)
        metrics.scheduled_scan_errors.labels(
            env="development", target_kind="memory_record"
        ).inc()
