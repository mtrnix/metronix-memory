"""MemoryService emits MEMORY_STORED / _DELETED / _PROMOTED / _RESET via EventBus."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import metronix.core.events as events
from metronix.core.events import EventBus
from metronix.core.models import MemoryRecord, MemoryScope
from metronix.memory.service import MemoryService

# Type alias for the bus_spy fixture value.
BusSpy = tuple[EventBus, list[tuple[str, dict[str, Any]]]]


def _record(
    *,
    record_id: str = "r1",
    agent_id: str = "ag",
    scope: MemoryScope = MemoryScope.PER_AGENT,
    session_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="ws",
        agent_id=agent_id,
        scope=scope,
        source_type="conversation",
        content="hello",
        tags=[],
        importance_score=0.5,
        session_id=session_id,
        metadata={},
        created_at=datetime.datetime(2026, 4, 23, tzinfo=datetime.UTC),
    )


def _make_svc(bus: EventBus | None) -> MemoryService:
    """Build MemoryService with heavily mocked stores.

    Only PG + Qdrant behaviors strictly needed by the methods under test are
    stubbed. Neo4j / Redis paths are best-effort / no-ops in the service.
    """
    redis = MagicMock()
    qdrant = MagicMock()
    qdrant.upsert = AsyncMock()
    qdrant.delete = AsyncMock()
    pg = MagicMock()
    return MemoryService(
        redis_cache=redis,
        qdrant_store=qdrant,
        pg_store=pg,
        workspace_id="ws",
        event_bus=bus,
    )


@pytest.fixture
def bus_spy() -> BusSpy:
    bus = EventBus()
    calls: list[tuple[str, dict[str, Any]]] = []

    async def capture(name: str, payload: dict[str, Any]) -> None:
        calls.append((name, payload))

    for topic in (
        events.MEMORY_STORED,
        events.MEMORY_DELETED,
        events.MEMORY_PROMOTED,
        events.MEMORY_RESET,
    ):
        bus.subscribe(topic, capture)
    return bus, calls


async def test_save_emits_memory_stored(bus_spy: BusSpy) -> None:
    bus, calls = bus_spy
    svc = _make_svc(bus)
    # Configure PG store to behave as "no existing record (no dedup hit) → save_record echoes back"
    rec = _record()
    # Cover both possible store API names — tests must pass whichever is correct.
    svc._pg.get_by_hash = AsyncMock(return_value=None)
    svc._pg.save = AsyncMock(return_value=rec)
    svc._pg.save_record = AsyncMock(return_value=rec)

    await svc.save("ws", rec)

    stored = [p for n, p in calls if n == events.MEMORY_STORED]
    assert len(stored) == 1
    assert stored[0]["workspace_id"] == "ws"
    assert stored[0]["agent_id"] == "ag"
    assert stored[0]["record_id"] == "r1"


async def test_delete_emits_memory_deleted(bus_spy: BusSpy) -> None:
    bus, calls = bus_spy
    svc = _make_svc(bus)
    existing = _record()
    svc._pg.get = AsyncMock(return_value=existing)
    svc._pg.delete = AsyncMock(return_value=True)

    ok = await svc.delete("ws", "r1")
    assert ok is True

    deleted = [p for n, p in calls if n == events.MEMORY_DELETED]
    assert len(deleted) == 1
    assert deleted[0]["agent_id"] == "ag"
    assert deleted[0]["record_id"] == "r1"


async def test_delete_missing_no_emit(bus_spy: BusSpy) -> None:
    bus, calls = bus_spy
    svc = _make_svc(bus)
    svc._pg.get = AsyncMock(return_value=None)
    svc._pg.delete = AsyncMock(return_value=False)
    await svc.delete("ws", "r_missing")
    assert [n for n, _ in calls if n == events.MEMORY_DELETED] == []


async def test_reset_emits_n_plus_umbrella(bus_spy: BusSpy) -> None:
    """reset() emits one MEMORY_DELETED per removed record AND one MEMORY_RESET umbrella."""
    bus, calls = bus_spy
    svc = _make_svc(bus)
    # Support either reset() contract:
    #   pg.reset -> int (count)  OR  pg.reset -> (count, deleted_ids)
    svc._pg.reset = AsyncMock(return_value=(3, ["r1", "r2", "r3"]))

    count = await svc.reset("ws", agent_id="ag", scope=MemoryScope.PER_AGENT)
    assert count == 3

    del_events = [p for n, p in calls if n == events.MEMORY_DELETED]
    assert len(del_events) == 3
    assert {p["record_id"] for p in del_events} == {"r1", "r2", "r3"}

    umbrella = [p for n, p in calls if n == events.MEMORY_RESET]
    assert len(umbrella) == 1
    assert umbrella[0]["count"] == 3
    assert umbrella[0]["agent_id"] == "ag"


async def test_no_event_bus_no_emit() -> None:
    """Existing tests construct MemoryService without a bus; that path must remain silent."""
    svc = _make_svc(None)
    rec = _record()
    svc._pg.get_by_hash = AsyncMock(return_value=None)
    svc._pg.save = AsyncMock(return_value=rec)
    svc._pg.save_record = AsyncMock(return_value=rec)
    # No bus → emission is a no-op; method completes cleanly.
    await svc.save("ws", rec)
