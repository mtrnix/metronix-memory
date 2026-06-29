"""Unit tests for Reconciler stage (MTRNIX-304, updated for MTRNIX-313).

Phase B rewires Reconciler through :class:`MemoryTarget`. Behavioural
contract is preserved for memory: same clean/duplicate/idempotent branches,
same ALIAS edge write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from metronix.core.models import MemoryRecord, MemoryScope, ReviewEntry
from metronix.memory.freshness.reconciler import Reconciler
from metronix.memory.freshness.target_memory import MemoryTarget


def _record(**overrides: object) -> MemoryRecord:
    defaults = {
        "id": "rec1",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "Payment integration uses webhook /stripe/callback.",
        "created_at": datetime(2026, 4, 20, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _build_reconciler(
    threshold: float = 0.85,
) -> tuple[Reconciler, MagicMock, AsyncMock, AsyncMock, AsyncMock]:
    pg = MagicMock()
    pg.get = AsyncMock()
    pg.update_lifecycle = AsyncMock()
    qdrant = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)
    coordination = AsyncMock()
    freshness_store = AsyncMock()
    rec = Reconciler(
        target=target,
        freshness_store=freshness_store,
        coordination=coordination,
        threshold=threshold,
    )
    return rec, pg, qdrant, coordination, freshness_store


# ``MemoryTarget.alias_edge`` goes through ``asyncio.to_thread`` calling the
# module-level ``alias_link_memory_items`` in the shared stages module.
_ALIAS_PATH = "metronix.freshness.stages.reconciler.alias_link_memory_items"


class TestReconciler:
    async def test_clean_state_emits_machine_event(self) -> None:
        rec, pg, qdrant, coord, fs = _build_reconciler()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [
            {"record_id": "rec1", "score": 1.0},  # self — skip
            {"record_id": "rec2", "score": 0.60},  # below threshold
        ]

        out = await rec.run("ws1", "rec1")

        assert out is None
        fs.save_review_entry.assert_not_awaited()
        # Clean state still produces the audit MachineEvent.
        fs.save_machine_event.assert_awaited()

    async def test_high_similarity_creates_review_entry(self) -> None:
        rec, pg, qdrant, coord, fs = _build_reconciler()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [
            {"record_id": "rec1", "score": 1.0},
            {"record_id": "rec2", "score": 0.91, "content": "duplicate text"},
        ]
        fs.find_review_entry.return_value = None
        fs.save_review_entry.side_effect = lambda entry: entry

        with patch(_ALIAS_PATH, return_value=None) as mock_alias:
            out = await rec.run("ws1", "rec1")

        assert isinstance(out, ReviewEntry)
        assert out.reason == "possible_duplicate"
        assert out.related_record_id == "rec2"
        assert out.target_kind == "memory_record"
        fs.save_review_entry.assert_awaited_once()
        mock_alias.assert_called_once()

    async def test_idempotent_does_not_duplicate_entry(self) -> None:
        rec, pg, qdrant, coord, fs = _build_reconciler()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [
            {"record_id": "rec1", "score": 1.0},
            {"record_id": "rec2", "score": 0.95},
        ]
        existing = ReviewEntry(
            id="existing",
            workspace_id="ws1",
            target_id="rec1",
            target_kind="memory_record",
            reason="possible_duplicate",
            related_record_id="rec2",
            content="",
            confidence=0.95,
        )
        fs.find_review_entry.return_value = existing

        with patch(_ALIAS_PATH, return_value=None):
            out = await rec.run("ws1", "rec1")

        # Returns the pre-existing entry, and does NOT create a new one.
        assert out is existing
        fs.save_review_entry.assert_not_awaited()

    async def test_mirror_pair_is_not_duplicated(self) -> None:
        """MTRNIX-395: if the reverse-direction entry exists, reuse it.

        When the partner record (rec2) was processed first it created
        (target=rec2, related=rec1). Processing rec1 must NOT create the
        mirror (target=rec1, related=rec2) — the pair is one finding.
        """
        rec, pg, qdrant, coord, fs = _build_reconciler()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [
            {"record_id": "rec1", "score": 1.0},
            {"record_id": "rec2", "score": 0.95},
        ]
        mirror = ReviewEntry(
            id="mirror",
            workspace_id="ws1",
            target_id="rec2",
            target_kind="memory_record",
            reason="possible_duplicate",
            related_record_id="rec1",
            content="",
            confidence=0.95,
        )
        # Forward lookup (target=rec1, related=rec2) → None; mirror lookup
        # (target=rec2, related=rec1) → the existing mirror entry.
        fs.find_review_entry.side_effect = [None, mirror]

        with patch(_ALIAS_PATH, return_value=None):
            out = await rec.run("ws1", "rec1")

        assert out is mirror
        fs.save_review_entry.assert_not_awaited()

    async def test_lock_contention_returns_none(self) -> None:
        rec, pg, qdrant, coord, _fs = _build_reconciler()
        coord.acquire_lock.return_value = None

        out = await rec.run("ws1", "rec1")

        assert out is None
        pg.get.assert_not_awaited()
        qdrant.search.assert_not_awaited()
