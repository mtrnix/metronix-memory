"""Unit tests for MemoryService review methods (MTRNIX-314)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.events import FRESHNESS_REVIEW_RESOLVED
from metatron.core.exceptions import MemoryNotFoundError
from metatron.core.models import (
    LifecycleStatus,
    MachineEvent,
    MemoryRecord,
    MemoryScope,
    ReviewEntry,
)
from metatron.memory.service import MemoryService


def _record(
    record_id: str = "mem001",
    status: LifecycleStatus = LifecycleStatus.REVIEW_NEEDED,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="ws1",
        agent_id="agent1",
        scope=MemoryScope.PER_AGENT,
        source_type="conversation",
        content="dark mode",
        tags=[],
        importance_score=0.5,
        ttl_expires_at=None,
        content_hash="h",
        session_id=None,
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=status,
    )


def _review(
    review_id: str = "r1",
    target_id: str = "mem001",
    reason: str = "possible_duplicate",
) -> ReviewEntry:
    return ReviewEntry(
        id=review_id,
        workspace_id="ws1",
        target_id=target_id,
        target_kind="memory_record",
        reason=reason,
        related_record_id=None,
        content="dup preview",
        confidence=0.8,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _make_service(
    *,
    freshness_store: MagicMock | None = None,
    event_bus: MagicMock | None = None,
    pg_store: MagicMock | None = None,
) -> tuple[MemoryService, dict]:
    pg = pg_store or MagicMock()
    qdrant = MagicMock()
    qdrant.update_payload = AsyncMock()
    redis = MagicMock()
    service = MemoryService(
        redis_cache=redis,
        qdrant_store=qdrant,
        pg_store=pg,
        workspace_id="ws1",
        freshness_store=freshness_store,
        event_bus=event_bus,
    )
    return service, {"pg": pg, "qdrant": qdrant, "redis": redis}


class TestListReviewEntries:
    async def test_delegates_to_freshness_store(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        fs.count_review_entries = AsyncMock(return_value=3)
        service, _ = _make_service(freshness_store=fs)

        entries, total = await service.list_review_entries(
            "ws1", reason="possible_duplicate", limit=5, offset=2
        )

        assert len(entries) == 1
        assert total == 3
        fs.list_review_entries.assert_awaited_once_with(
            "ws1",
            target_kind="memory_record",
            record_id=None,
            reason="possible_duplicate",
            limit=5,
            offset=2,
        )
        fs.count_review_entries.assert_awaited_once_with(
            "ws1",
            target_kind="memory_record",
            record_id=None,
            reason="possible_duplicate",
        )

    async def test_raises_when_freshness_store_not_wired(self) -> None:
        service, _ = _make_service(freshness_store=None)
        with pytest.raises(RuntimeError, match="freshness_store"):
            await service.list_review_entries("ws1")


class TestResolveReviewKeep:
    async def test_keep_transitions_to_active_and_deletes_review(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        fs.delete_review_entry = AsyncMock(return_value=True)
        fs.save_machine_event = AsyncMock(
            side_effect=lambda evt: MachineEvent(
                id="evt001",
                workspace_id=evt.workspace_id,
                event_type=evt.event_type,
                actor=evt.actor,
                target_kind=evt.target_kind,
                target_id=evt.target_id,
                payload=evt.payload,
                created_at=evt.created_at,
            )
        )
        pg = MagicMock()
        pg.get = AsyncMock(return_value=_record())
        pg.update_lifecycle = AsyncMock(return_value=_record(status=LifecycleStatus.ACTIVE))

        event_bus = MagicMock()
        event_bus.emit = AsyncMock()
        service, deps = _make_service(freshness_store=fs, event_bus=event_bus, pg_store=pg)

        resolution = await service.resolve_review(
            "ws1", review_id="r1", action="keep", notes="agent kept it"
        )

        assert resolution.review_id == "r1"
        assert resolution.target_id == "mem001"
        assert resolution.action == "keep"
        assert resolution.old_status == "review_needed"
        assert resolution.new_status == "active"
        assert resolution.superseded_by is None
        assert resolution.machine_event_id == "evt001"

        # PG update called with ACTIVE + verification_state.
        pg.update_lifecycle.assert_awaited_once()
        kw = pg.update_lifecycle.await_args.kwargs
        assert kw["status"] == LifecycleStatus.ACTIVE
        assert kw["verification_state"] == "keep_resolved"
        assert kw.get("superseded_by") is None

        fs.delete_review_entry.assert_awaited_once_with("ws1", "r1")
        fs.save_machine_event.assert_awaited_once()
        saved_evt = fs.save_machine_event.await_args.args[0]
        assert saved_evt.event_type == "freshness_review_resolved"
        assert saved_evt.actor == "mcp_caller"
        assert saved_evt.payload["action"] == "keep"
        assert saved_evt.payload["notes"] == "agent kept it"

        # Qdrant payload synced best-effort.
        deps["qdrant"].update_payload.assert_awaited_once_with("mem001", {"status": "active"})

        # EventBus fired.
        event_bus.emit.assert_awaited_once()
        emit_args = event_bus.emit.await_args.args
        assert emit_args[0] == FRESHNESS_REVIEW_RESOLVED
        assert emit_args[1]["action"] == "keep"


class TestResolveReviewArchive:
    async def test_archive_transitions_to_archived(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        fs.delete_review_entry = AsyncMock(return_value=True)
        fs.save_machine_event = AsyncMock(side_effect=lambda evt: evt)
        pg = MagicMock()
        pg.get = AsyncMock(return_value=_record())
        pg.update_lifecycle = AsyncMock(return_value=_record(status=LifecycleStatus.ARCHIVED))
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        resolution = await service.resolve_review("ws1", review_id="r1", action="archive")

        assert resolution.new_status == "archived"
        kw = pg.update_lifecycle.await_args.kwargs
        assert kw["status"] == LifecycleStatus.ARCHIVED
        assert kw["verification_state"] == "archived_via_review"


class TestResolveReviewMerge:
    async def test_merge_into_existing_target_sets_superseded_by(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        fs.delete_review_entry = AsyncMock(return_value=True)
        fs.save_machine_event = AsyncMock(side_effect=lambda evt: evt)
        pg = MagicMock()
        # First get: source record. Second get: merge target.
        pg.get = AsyncMock(
            side_effect=[
                _record(),  # source
                _record(record_id="mem_target", status=LifecycleStatus.ACTIVE),
            ]
        )
        pg.update_lifecycle = AsyncMock(return_value=_record(status=LifecycleStatus.SUPERSEDED))
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        resolution = await service.resolve_review(
            "ws1", review_id="r1", action="merge_into:mem_target"
        )

        assert resolution.action == "merge_into"
        assert resolution.new_status == "superseded"
        assert resolution.superseded_by == "mem_target"

        kw = pg.update_lifecycle.await_args.kwargs
        assert kw["status"] == LifecycleStatus.SUPERSEDED
        assert kw["superseded_by"] == "mem_target"
        assert kw["verification_state"] == "merged_via_review"

    async def test_merge_into_missing_target_raises(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        pg = MagicMock()
        pg.get = AsyncMock(side_effect=[_record(), None])  # target missing
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        with pytest.raises(ValueError, match="merge_into target"):
            await service.resolve_review("ws1", review_id="r1", action="merge_into:mem_missing")

    async def test_merge_into_empty_target_raises(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        pg = MagicMock()
        pg.get = AsyncMock(return_value=_record())
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        with pytest.raises(ValueError):
            await service.resolve_review("ws1", review_id="r1", action="merge_into:")


class TestResolveReviewDiscard:
    async def test_discard_soft_archives(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        fs.delete_review_entry = AsyncMock(return_value=True)
        fs.save_machine_event = AsyncMock(side_effect=lambda evt: evt)
        pg = MagicMock()
        pg.get = AsyncMock(return_value=_record())
        pg.update_lifecycle = AsyncMock(return_value=_record(status=LifecycleStatus.ARCHIVED))
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        resolution = await service.resolve_review("ws1", review_id="r1", action="discard")

        assert resolution.new_status == "archived"
        kw = pg.update_lifecycle.await_args.kwargs
        assert kw["status"] == LifecycleStatus.ARCHIVED
        assert kw["verification_state"] == "discarded_via_review"


class TestResolveReviewErrors:
    async def test_review_not_found_raises(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[])  # empty
        pg = MagicMock()
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        with pytest.raises(MemoryNotFoundError, match="Review entry"):
            await service.resolve_review("ws1", review_id="r_missing", action="keep")

    async def test_record_not_found_raises(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        pg = MagicMock()
        pg.get = AsyncMock(return_value=None)  # target record gone
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        with pytest.raises(MemoryNotFoundError, match="Record"):
            await service.resolve_review("ws1", review_id="r1", action="keep")

    async def test_unknown_action_raises(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        pg = MagicMock()
        pg.get = AsyncMock(return_value=_record())
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        with pytest.raises(ValueError, match="Unknown action"):
            await service.resolve_review("ws1", review_id="r1", action="bogus_action")

    async def test_raises_without_freshness_store(self) -> None:
        service, _ = _make_service(freshness_store=None)

        with pytest.raises(RuntimeError, match="freshness_store"):
            await service.resolve_review("ws1", review_id="r1", action="keep")

    async def test_notes_truncated_to_1024(self) -> None:
        fs = MagicMock()
        fs.list_review_entries = AsyncMock(return_value=[_review()])
        fs.delete_review_entry = AsyncMock(return_value=True)

        saved_events = []

        def capture(evt: MachineEvent) -> MachineEvent:
            saved_events.append(evt)
            return evt

        fs.save_machine_event = AsyncMock(side_effect=capture)
        pg = MagicMock()
        pg.get = AsyncMock(return_value=_record())
        pg.update_lifecycle = AsyncMock(return_value=_record(status=LifecycleStatus.ACTIVE))
        service, _ = _make_service(freshness_store=fs, pg_store=pg)

        long_notes = "x" * 5000
        await service.resolve_review("ws1", review_id="r1", action="keep", notes=long_notes)

        assert saved_events
        assert len(saved_events[0].payload["notes"]) == 1024


class TestSearchStatusFilterPlumbing:
    async def test_search_passes_status_filter_through(self) -> None:
        search = MagicMock()
        search.hybrid_search = AsyncMock(return_value=[])
        pg = MagicMock()
        service = MemoryService(
            redis_cache=MagicMock(),
            qdrant_store=MagicMock(),
            pg_store=pg,
            workspace_id="ws1",
            search=search,
        )

        await service.search(
            "ws1",
            "query",
            agent_id="agent1",
            status_filter=[LifecycleStatus.ACTIVE],
        )

        kw = search.hybrid_search.await_args.kwargs
        assert kw["status_filter"] == [LifecycleStatus.ACTIVE]
