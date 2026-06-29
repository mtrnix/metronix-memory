"""QUERY_EXECUTED + DOCUMENT_ACCESSED share a correlation_id (helper-level test)."""

from __future__ import annotations

import pytest

from metronix.core.events import DOCUMENT_ACCESSED, QUERY_EXECUTED, EventBus
from metronix.retrieval.search import _emit_search_events


@pytest.fixture
def bus_and_calls() -> tuple[EventBus, list[tuple[str, dict]]]:
    bus = EventBus()
    calls: list[tuple[str, dict]] = []

    async def capture(n: str, p: dict) -> None:
        calls.append((n, p))

    bus.subscribe(QUERY_EXECUTED, capture)
    bus.subscribe(DOCUMENT_ACCESSED, capture)
    return bus, calls


async def test_helper_emits_single_query_and_per_channel_documents(bus_and_calls) -> None:
    bus, calls = bus_and_calls
    docs_by_channel = {
        "dense": ["doc-1", "doc-2"],
        "exact": ["doc-3"],
        "graph": [],  # empty channels must NOT emit document_accessed
    }
    await _emit_search_events(
        bus=bus,
        workspace_id="ws",
        agent_id="ag",
        session_id="s1",
        source="mcp",
        query="what is X",
        top_k=5,
        result_count=3,
        duration_ms=42,
        docs_by_channel=docs_by_channel,
    )

    qprocessed = [p for n, p in calls if n == QUERY_EXECUTED]
    daccessed = [p for n, p in calls if n == DOCUMENT_ACCESSED]

    assert len(qprocessed) == 1, "exactly one QUERY_EXECUTED"
    assert len(daccessed) == 2, "one DOCUMENT_ACCESSED per non-empty channel"

    # All events share the correlation_id
    cid = qprocessed[0]["correlation_id"]
    assert isinstance(cid, str) and len(cid) >= 32
    for p in daccessed:
        assert p["correlation_id"] == cid

    # Query payload shape
    assert qprocessed[0]["workspace_id"] == "ws"
    assert qprocessed[0]["agent_id"] == "ag"
    assert qprocessed[0]["session_id"] == "s1"
    assert qprocessed[0]["source"] == "mcp"
    assert qprocessed[0]["query"] == "what is X"
    assert qprocessed[0]["top_k"] == 5
    assert qprocessed[0]["result_count"] == 3
    assert qprocessed[0]["duration_ms"] == 42

    # Per-channel payload shape
    channels_seen = {p["channel"] for p in daccessed}
    assert channels_seen == {"dense", "exact"}
    for p in daccessed:
        if p["channel"] == "dense":
            assert p["document_ids"] == ["doc-1", "doc-2"]
        elif p["channel"] == "exact":
            assert p["document_ids"] == ["doc-3"]


async def test_helper_noop_without_bus(bus_and_calls) -> None:
    # bus=None → no emissions anywhere (used when plugin_manager is None)
    await _emit_search_events(
        bus=None,
        workspace_id="ws",
        agent_id="ag",
        session_id=None,
        source="rest",
        query="x",
        top_k=5,
        result_count=0,
        duration_ms=1,
        docs_by_channel={"dense": ["a"]},
    )
    # Nothing should have been emitted (no bus to subscribe on anyway, but at
    # minimum the helper returns a valid empty correlation and no exception).


async def test_helper_noop_without_agent_id(bus_and_calls) -> None:
    bus, calls = bus_and_calls
    # No agent_id (neither kwarg nor contextvar) → no emissions.
    await _emit_search_events(
        bus=bus,
        workspace_id="ws",
        agent_id=None,
        session_id=None,
        source="rest",
        query="x",
        top_k=5,
        result_count=0,
        duration_ms=1,
        docs_by_channel={"dense": ["a"]},
    )
    assert calls == []


async def test_helper_truncates_long_query(bus_and_calls) -> None:
    bus, calls = bus_and_calls
    long_q = "x" * 1000
    await _emit_search_events(
        bus=bus,
        workspace_id="ws",
        agent_id="ag",
        session_id=None,
        source="rest",
        query=long_q,
        top_k=5,
        result_count=1,
        duration_ms=1,
        docs_by_channel={"dense": ["a"]},
    )
    qpayload = next(p for n, p in calls if n == QUERY_EXECUTED)
    assert len(qpayload["query"]) == 256


async def test_helper_caps_document_ids_per_event(bus_and_calls) -> None:
    bus, calls = bus_and_calls
    many_ids = [f"d{i}" for i in range(200)]
    await _emit_search_events(
        bus=bus,
        workspace_id="ws",
        agent_id="ag",
        session_id=None,
        source="rest",
        query="x",
        top_k=5,
        result_count=200,
        duration_ms=1,
        docs_by_channel={"dense": many_ids},
    )
    daccessed = next(p for n, p in calls if n == DOCUMENT_ACCESSED)
    assert len(daccessed["document_ids"]) == 50  # hard cap to keep JSONB small
