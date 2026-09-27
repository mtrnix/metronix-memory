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
    contradiction_scorer: object | None = None,
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
        contradiction_scorer=contradiction_scorer,
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


class _Scorer:
    """Contradiction scores by related content; records the pairs it saw."""

    def __init__(self, by_content: dict[str, float], fail: bool = False) -> None:
        self.by_content = by_content
        self.fail = fail
        self.pairs: list[tuple[str, str]] = []

    def contradiction_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        if self.fail:
            raise RuntimeError("model unavailable")
        self.pairs.extend(pairs)
        return [self.by_content.get(b, 0.0) for _, b in pairs]


class TestReconcilerContradiction:
    """#516: with a scorer, contradicting pairs become possible_contradiction."""

    def _setup(self, scorer: _Scorer, hits: list[dict]):
        rec, pg, qdrant, coord, fs = _build_reconciler(contradiction_scorer=scorer)
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(content="The API rate limit is 100 requests per minute.")
        qdrant.search.return_value = [{"record_id": "rec1", "score": 1.0}, *hits]
        fs.find_review_entry.return_value = None
        fs.save_review_entry.side_effect = lambda entry: entry
        return rec, fs

    async def test_contradiction_is_filed_without_alias_edge(self) -> None:
        scorer = _Scorer({"The limit is 1000 per minute.": 0.97})
        rec, fs = self._setup(
            scorer,
            [{"record_id": "rec2", "score": 0.93, "content": "The limit is 1000 per minute."}],
        )

        with patch(_ALIAS_PATH, return_value=None) as mock_alias:
            out = await rec.run("ws1", "rec1")

        assert out.reason == "possible_contradiction"
        assert out.related_record_id == "rec2"
        assert out.confidence == 0.97
        assert scorer.pairs == [
            ("The API rate limit is 100 requests per minute.", "The limit is 1000 per minute.")
        ]
        mock_alias.assert_not_called()
        payload = fs.save_machine_event.await_args.args[0].payload
        assert payload["reason"] == "possible_contradiction"

    async def test_below_threshold_stays_a_duplicate(self) -> None:
        scorer = _Scorer({"Up to 100 requests every minute.": 0.02})
        rec, _fs = self._setup(
            scorer,
            [{"record_id": "rec2", "score": 0.95, "content": "Up to 100 requests every minute."}],
        )

        with patch(_ALIAS_PATH, return_value=None) as mock_alias:
            out = await rec.run("ws1", "rec1")

        assert out.reason == "possible_duplicate"
        assert out.confidence == 0.95
        mock_alias.assert_called_once()

    async def test_contradiction_outranks_a_closer_duplicate(self) -> None:
        scorer = _Scorer({"Same limit, 100 a minute.": 0.01, "Now 1000 a minute.": 0.9})
        rec, _fs = self._setup(
            scorer,
            [
                {"record_id": "rec2", "score": 0.96, "content": "Same limit, 100 a minute."},
                {"record_id": "rec3", "score": 0.88, "content": "Now 1000 a minute."},
                {"record_id": "rec4", "score": 0.40, "content": "Unrelated."},
            ],
        )

        with patch(_ALIAS_PATH, return_value=None):
            out = await rec.run("ws1", "rec1")

        assert out.reason == "possible_contradiction"
        assert out.related_record_id == "rec3"
        # Only pairs above the cosine gate are scored.
        assert [b for _, b in scorer.pairs] == ["Same limit, 100 a minute.", "Now 1000 a minute."]

    async def test_scorer_failure_falls_back_to_duplicate(self) -> None:
        scorer = _Scorer({}, fail=True)
        rec, _fs = self._setup(
            scorer,
            [{"record_id": "rec2", "score": 0.93, "content": "The limit is 1000 per minute."}],
        )

        with patch(_ALIAS_PATH, return_value=None):
            out = await rec.run("ws1", "rec1")

        assert out.reason == "possible_duplicate"
