"""Tests for scripts/backfill_memory_simhash.py (PROJ-277).

The backfill script is thin — tests focus on the async helper (_process_workspace
and _run) by monkey-patching MemoryPostgresStore and the engine.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

# Make the scripts/ directory importable.
_SCRIPTS_DIR = str(Path(__file__).parent.parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from backfill_memory_simhash import _process_workspace  # noqa: E402

from metronix.ingestion.dedup import simhash  # noqa: E402

# ---------------------------------------------------------------------------
# Async generator helper
# ---------------------------------------------------------------------------


async def _gen(*batches):
    """Yield batches from a list — simulates iter_records_missing_simhash."""
    for batch in batches:
        yield batch


# ---------------------------------------------------------------------------
# _process_workspace
# ---------------------------------------------------------------------------


class TestProcessWorkspace:
    async def test_dry_run_scans_but_does_not_write(self) -> None:
        pg = AsyncMock()
        pg.iter_records_missing_simhash = lambda ws, batch_size, **kwargs: _gen(
            [("r1", "hello world"), ("r2", "foo bar")]
        )
        pg.bulk_set_simhash = AsyncMock(return_value=0)

        scanned, updated = await _process_workspace(pg, "ws1", batch_size=500, dry_run=True)

        assert scanned == 2
        assert updated == 0
        pg.bulk_set_simhash.assert_not_awaited()

    async def test_real_run_writes_simhash(self) -> None:
        content1 = "the quick brown fox"
        content2 = "hello world again"
        pg = AsyncMock()
        pg.iter_records_missing_simhash = lambda ws, batch_size, **kwargs: _gen(
            [("r1", content1), ("r2", content2)]
        )
        pg.bulk_set_simhash = AsyncMock(return_value=2)

        scanned, updated = await _process_workspace(pg, "ws1", batch_size=500, dry_run=False)

        assert scanned == 2
        assert updated == 2
        pg.bulk_set_simhash.assert_awaited_once()
        call_rows = pg.bulk_set_simhash.call_args[0][0]
        assert ("r1", simhash(content1)) in call_rows
        assert ("r2", simhash(content2)) in call_rows

    async def test_idempotent_empty_batch_returns_zero(self) -> None:
        """If iter returns nothing (all rows backfilled), nothing is written."""
        pg = AsyncMock()
        pg.iter_records_missing_simhash = lambda ws, batch_size, **kwargs: _gen()  # no batches
        pg.bulk_set_simhash = AsyncMock(return_value=0)

        scanned, updated = await _process_workspace(pg, "ws1", batch_size=500, dry_run=False)

        assert scanned == 0
        assert updated == 0
        pg.bulk_set_simhash.assert_not_awaited()

    async def test_batched_processing_accumulates_counts(self) -> None:
        """Multiple batches from the iterator are each processed."""
        pg = AsyncMock()
        pg.iter_records_missing_simhash = lambda ws, batch_size, **kwargs: _gen(
            [("r1", "batch one")],
            [("r2", "batch two"), ("r3", "batch three")],
        )
        pg.bulk_set_simhash = AsyncMock(return_value=1)

        scanned, updated = await _process_workspace(pg, "ws1", batch_size=1, dry_run=False)

        assert scanned == 3
        # bulk_set_simhash was called twice (once per batch), each returning 1.
        assert updated == 2
        assert pg.bulk_set_simhash.await_count == 2

    async def test_empty_content_simhash_is_zero(self) -> None:
        """Empty content hashes to 0; bulk_set_simhash still receives the row."""
        pg = AsyncMock()
        pg.iter_records_missing_simhash = lambda ws, batch_size, **kwargs: _gen([("r1", "")])
        pg.bulk_set_simhash = AsyncMock(return_value=1)

        scanned, updated = await _process_workspace(pg, "ws1", batch_size=500, dry_run=False)

        assert scanned == 1
        assert updated == 1
        call_rows = pg.bulk_set_simhash.call_args[0][0]
        # simhash("") == 0 is fine — the store will persist it.
        assert call_rows[0] == ("r1", simhash(""))

    async def test_workspace_none_passes_none_to_store(self) -> None:
        """workspace_id=None means iterate all workspaces — None is forwarded."""
        received_ws: list = []

        async def _mock_iter(ws: str | None, batch_size: int, **kwargs):
            received_ws.append(ws)
            # Make it a proper async generator by using `if False: yield`
            if False:  # noqa: SIM210
                yield []

        pg = AsyncMock()
        pg.iter_records_missing_simhash = _mock_iter

        scanned, updated = await _process_workspace(pg, None, batch_size=500, dry_run=True)

        assert received_ws == [None]
        assert scanned == 0
