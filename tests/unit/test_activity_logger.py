"""ActivityLogger translates EventBus payloads into ActivityRow writes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from metronix.activity.context import bind_agent_id, current_agent_id
from metronix.activity.logger import ActivityLogger
from metronix.core.events import (
    AGENT_CREATED,
    DOCUMENT_ACCESSED,
    ERROR_OCCURRED,
    MEMORY_DELETED,
    MEMORY_PROMOTED,
    MEMORY_RESET,
    MEMORY_STORED,
    QUERY_EXECUTED,
    TOOL_CALLED,
    EventBus,
)


@pytest.fixture
def store() -> AsyncMock:
    m = AsyncMock()
    m.insert = AsyncMock()
    return m


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


async def test_memory_stored_writes_row(bus: EventBus, store: AsyncMock) -> None:
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)

    await bus.emit(
        MEMORY_STORED,
        {
            "workspace_id": "ws",
            "agent_id": "ag",
            "record_id": "r1",
            "scope": "per_agent",
        },
    )

    assert store.insert.await_count == 1
    row = store.insert.await_args.args[0]
    assert row.workspace_id == "ws"
    assert row.agent_id == "ag"
    assert row.event_type == "memory.created"
    assert row.event_data["record_id"] == "r1"


async def test_missing_agent_id_is_skipped(bus: EventBus, store: AsyncMock) -> None:
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)
    await bus.emit(QUERY_EXECUTED, {"workspace_id": "ws"})  # no agent_id
    assert store.insert.await_count == 0


async def test_missing_workspace_id_is_skipped(bus: EventBus, store: AsyncMock) -> None:
    """Symmetric to missing-agent-id: no workspace → drop with warning."""
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)
    await bus.emit(MEMORY_STORED, {"agent_id": "ag", "record_id": "r1"})  # no ws_id
    assert store.insert.await_count == 0


async def test_context_var_fallback(bus: EventBus, store: AsyncMock) -> None:
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)
    token = bind_agent_id("ag_ctx")
    try:
        await bus.emit(
            QUERY_EXECUTED,
            {
                "workspace_id": "ws",
                "correlation_id": "c1",
                "query": "hi",
                "top_k": 5,
                "result_count": 1,
                "duration_ms": 10,
                "source": "mcp",
            },
        )
    finally:
        current_agent_id.reset(token)
    assert store.insert.await_count == 1
    row = store.insert.await_args.args[0]
    assert row.agent_id == "ag_ctx"
    assert row.event_type == "query.processed"


async def test_payload_projection_for_tool_called(bus: EventBus, store: AsyncMock) -> None:
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)
    payload = {
        "workspace_id": "ws",
        "agent_id": "ag",
        "session_id": "s",
        "tool_name": "memory_store",
        "arguments": {"a": 1},
        "arguments_truncated": False,
        "duration_ms": 7,
        "success": True,
    }
    await bus.emit(TOOL_CALLED, payload)
    row = store.insert.await_args.args[0]
    assert row.event_type == "tool.called"
    assert row.event_data["tool_name"] == "memory_store"
    assert row.event_data["arguments"] == {"a": 1}
    assert row.event_data["success"] is True
    # reserved keys must NOT appear in event_data
    assert "workspace_id" not in row.event_data
    assert "agent_id" not in row.event_data
    assert "session_id" not in row.event_data


async def test_reset_event_maps_to_memory_reset(bus: EventBus, store: AsyncMock) -> None:
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)
    await bus.emit(
        MEMORY_RESET,
        {"workspace_id": "ws", "agent_id": "ag", "scope": None, "count": 3},
    )
    row = store.insert.await_args.args[0]
    assert row.event_type == "memory.reset"
    assert row.event_data["count"] == 3


async def test_all_mapped_topics_route_correctly(bus: EventBus, store: AsyncMock) -> None:
    logger = ActivityLogger(store=store)
    logger.subscribe(bus)
    cases: list[tuple[str, dict[str, Any], str]] = [
        (
            MEMORY_DELETED,
            {"workspace_id": "w", "agent_id": "a", "record_id": "r"},
            "memory.deleted",
        ),
        (
            MEMORY_PROMOTED,
            {
                "workspace_id": "w",
                "agent_id": "a",
                "record_id": "r",
                "from_scope": "session",
                "to_scope": "per_agent",
            },
            "memory.promoted",
        ),
        (
            DOCUMENT_ACCESSED,
            {
                "workspace_id": "w",
                "agent_id": "a",
                "correlation_id": "c",
                "document_ids": ["d"],
                "channel": "dense",
            },
            "document.accessed",
        ),
        (
            AGENT_CREATED,
            {
                "workspace_id": "w",
                "agent_id": "a",
                "config_version": 1,
                "created_by": "u",
            },
            "agent.created",
        ),
        (
            ERROR_OCCURRED,
            {
                "workspace_id": "w",
                "agent_id": "a",
                "source": "tool",
                "error_type": "ValueError",
                "error_message": "boom",
            },
            "error",
        ),
    ]
    for topic, payload, expected in cases:
        store.insert.reset_mock()
        await bus.emit(topic, payload)
        assert store.insert.await_args.args[0].event_type == expected
