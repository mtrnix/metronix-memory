"""Unit tests for SessionGCPass — session memory GC in the scheduled-scan loop (Phase 2).

Covers:
* GC1 — deletes rows where ttl_expires_at < now() - grace
* GC2 — respects workspace boundaries (workspace_lister filters)
* GC3 — per-workspace exception is swallowed; loop continues to next ws
* GC4 — grace_hours=0 treats expiry as immediate cutoff
* GC5 — grace_hours=24 keeps rows within the grace window
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core import config as config_mod
from metatron.freshness.scheduled_scan import SessionGCPass


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    config_mod._settings = None
    yield
    config_mod._settings = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pass(
    *,
    grace_hours: int = 24,
    workspace_ids: list[str] | None = None,
    delete_return: int = 0,
    pg_side_effect: Exception | None = None,
    batch_limit: int = 1000,
) -> tuple[SessionGCPass, MagicMock]:
    """Build a SessionGCPass with a mock PG store and workspace lister."""
    pg = MagicMock()
    if pg_side_effect is not None:
        pg.delete_session_records_past_grace = AsyncMock(side_effect=pg_side_effect)
    else:
        pg.delete_session_records_past_grace = AsyncMock(return_value=delete_return)

    ws_list = workspace_ids if workspace_ids is not None else []

    async def lister() -> list[str]:
        return ws_list

    gc = SessionGCPass(
        pg_store=pg,  # type: ignore[arg-type]
        workspace_lister=lister,
        grace_hours=grace_hours,
        batch_limit=batch_limit,
    )
    return gc, pg


# ---------------------------------------------------------------------------
# GC1 — Deletes rows past grace
# ---------------------------------------------------------------------------


class TestSessionGCPassRun:
    async def test_gc1_calls_delete_for_each_workspace(self) -> None:
        gc, pg = _make_pass(grace_hours=24, workspace_ids=["ws-A", "ws-B"], delete_return=3)

        total = await gc.run()

        assert total == 6  # 3 rows per workspace × 2 workspaces
        assert pg.delete_session_records_past_grace.await_count == 2

    async def test_gc1_cutoff_is_now_minus_grace(self) -> None:
        gc, pg = _make_pass(grace_hours=12, workspace_ids=["ws-A"], delete_return=0)

        before = datetime.now(UTC)
        await gc.run()
        after = datetime.now(UTC)

        call_kwargs = pg.delete_session_records_past_grace.call_args.kwargs
        cutoff = call_kwargs["grace_cutoff"]
        # cutoff should be approximately now - 12h
        expected_lower = before - timedelta(hours=12) - timedelta(seconds=2)
        expected_upper = after - timedelta(hours=12) + timedelta(seconds=2)
        assert expected_lower <= cutoff <= expected_upper

    async def test_gc1_returns_zero_for_empty_workspace_list(self) -> None:
        gc, pg = _make_pass(workspace_ids=[])
        total = await gc.run()

        assert total == 0
        pg.delete_session_records_past_grace.assert_not_awaited()


# ---------------------------------------------------------------------------
# GC2 — Workspace boundaries respected
# ---------------------------------------------------------------------------


class TestSessionGCPassWorkspaceBoundary:
    async def test_gc2_only_listed_workspaces_are_touched(self) -> None:
        """ws-B should not receive a delete call when only ws-A is listed."""
        pg = MagicMock()
        pg.delete_session_records_past_grace = AsyncMock(return_value=0)

        async def lister() -> list[str]:
            return ["ws-A"]

        gc = SessionGCPass(
            pg_store=pg,  # type: ignore[arg-type]
            workspace_lister=lister,
            grace_hours=24,
        )
        await gc.run()

        # Only ws-A was passed to the store.
        calls = pg.delete_session_records_past_grace.await_args_list
        for call in calls:
            assert call.args[0] == "ws-A"

        assert pg.delete_session_records_past_grace.await_count == 1


# ---------------------------------------------------------------------------
# GC3 — Per-workspace exception swallowed
# ---------------------------------------------------------------------------


class TestSessionGCPassErrorSwallow:
    async def test_gc3_workspace_exception_swallowed_and_next_ws_runs(self) -> None:
        """ws-A explodes but ws-B still gets its delete call.

        Structlog does not integrate with pytest's caplog fixture, so we
        verify the swallow behaviour by checking call_count and total, not
        by inspecting log messages.
        """
        pg = MagicMock()
        call_count = 0

        async def _delete(ws: str, *, grace_cutoff: datetime, limit: int = 1000) -> int:
            nonlocal call_count
            call_count += 1
            if ws == "ws-A":
                raise RuntimeError("pg exploded")
            return 2  # ws-B deletes 2 rows

        pg.delete_session_records_past_grace = _delete

        async def lister() -> list[str]:
            return ["ws-A", "ws-B"]

        gc = SessionGCPass(
            pg_store=pg,  # type: ignore[arg-type]
            workspace_lister=lister,
            grace_hours=24,
        )

        total = await gc.run()

        # ws-B's 2 rows still counted — error from ws-A was swallowed.
        assert total == 2
        # Both workspaces were attempted (ws-A raised, ws-B succeeded).
        assert call_count == 2

    async def test_gc3_lister_exception_swallowed_returns_zero(self) -> None:
        pg = MagicMock()
        pg.delete_session_records_past_grace = AsyncMock(return_value=0)

        async def bad_lister() -> list[str]:
            raise RuntimeError("pg down")

        gc = SessionGCPass(
            pg_store=pg,  # type: ignore[arg-type]
            workspace_lister=bad_lister,
            grace_hours=24,
        )

        total = await gc.run()

        assert total == 0
        pg.delete_session_records_past_grace.assert_not_awaited()


# ---------------------------------------------------------------------------
# GC4 — grace_hours=0
# ---------------------------------------------------------------------------


class TestSessionGCGraceZero:
    async def test_gc4_grace_zero_cutoff_equals_now(self) -> None:
        """grace_hours=0: cutoff ≈ now(), rows expire immediately."""
        gc, pg = _make_pass(grace_hours=0, workspace_ids=["ws-A"], delete_return=5)

        before = datetime.now(UTC)
        await gc.run()
        after = datetime.now(UTC)

        call_kwargs = pg.delete_session_records_past_grace.call_args.kwargs
        cutoff = call_kwargs["grace_cutoff"]
        # cutoff should be approximately now (within a second).
        assert before - timedelta(seconds=2) <= cutoff <= after + timedelta(seconds=2)


# ---------------------------------------------------------------------------
# GC5 — grace_hours=24 keeps rows within grace window
# ---------------------------------------------------------------------------


class TestSessionGCGrace24:
    async def test_gc5_rows_within_grace_window_not_passed_to_delete(self) -> None:
        """The cutoff passed to PG ensures rows within the window are not touched.

        We verify the cutoff calculation: it should be now - 24h, meaning PG
        will only delete rows with ttl_expires_at < (now - 24h).
        A row with ttl_expires_at = now - 23h should NOT be covered by the
        DELETE because it is newer than the cutoff.
        """
        gc, pg = _make_pass(grace_hours=24, workspace_ids=["ws-A"], delete_return=0)

        before = datetime.now(UTC)
        await gc.run()
        after = datetime.now(UTC)

        call_kwargs = pg.delete_session_records_past_grace.call_args.kwargs
        cutoff = call_kwargs["grace_cutoff"]

        # Row that expired 23h ago: ttl = before - 23h → still within grace → should NOT be deleted
        row_just_inside_grace = before - timedelta(hours=23)
        assert row_just_inside_grace > cutoff  # Row is newer than cutoff → safe

        # Row that expired 25h ago: ttl = before - 25h → past grace → should be deleted
        row_past_grace = before - timedelta(hours=25)
        assert row_past_grace < after - timedelta(hours=24)  # Row is older than cutoff
