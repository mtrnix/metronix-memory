"""AgentRegistryService emits lifecycle events via EventBus."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.agents.models import AgentRecord, AgentStatus
from metronix.agents.service import AgentRegistryService
from metronix.core.events import (
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_STATUS_CHANGED,
    AGENT_UPDATED,
    EventBus,
)


def _sample_record(
    *,
    agent_id: str = "ag_1",
    status: AgentStatus = AgentStatus.STOPPED,
    config_version: int = 1,
) -> AgentRecord:
    now = datetime(2026, 4, 23, tzinfo=UTC)
    return AgentRecord(
        id=agent_id,
        workspace_id="ws",
        name="one",
        status=status,
        model="m",
        capabilities=[],
        tools=[],
        memory_bindings={},
        budget={},
        config_version=config_version,
        current_config={},
        created_by="u",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def bus_spy() -> tuple[EventBus, list[tuple[str, dict[str, Any]]]]:
    bus = EventBus()
    calls: list[tuple[str, dict[str, Any]]] = []

    async def capture(name: str, payload: dict[str, Any]) -> None:
        calls.append((name, payload))

    for topic in (
        AGENT_CREATED,
        AGENT_UPDATED,
        AGENT_STATUS_CHANGED,
        AGENT_DELETED,
    ):
        bus.subscribe(topic, capture)
    return bus, calls


async def test_create_emits_agent_created(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, Any]]]],
) -> None:
    bus, calls = bus_spy
    repo = MagicMock()
    repo.save_new = AsyncMock(return_value=_sample_record())
    svc = AgentRegistryService(repo, workspace_id="ws", event_bus=bus)

    await svc.create_agent(name="one", model="m", created_by="u")

    names = [n for n, _ in calls]
    assert AGENT_CREATED in names
    payload = next(p for n, p in calls if n == AGENT_CREATED)
    assert payload["workspace_id"] == "ws"
    assert payload["agent_id"] == "ag_1"
    assert payload["config_version"] == 1
    assert payload["created_by"] == "u"


async def test_update_emits_agent_updated(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, Any]]]],
) -> None:
    bus, calls = bus_spy
    updated = _sample_record(config_version=2)
    repo = MagicMock()
    repo.update_with_version_bump = AsyncMock(return_value=updated)
    repo.get = AsyncMock(return_value=_sample_record())
    svc = AgentRegistryService(repo, workspace_id="ws", event_bus=bus)

    await svc.update_agent("ag_1", name="renamed", changed_by="u")

    names = [n for n, _ in calls]
    assert AGENT_UPDATED in names
    payload = next(p for n, p in calls if n == AGENT_UPDATED)
    assert payload["agent_id"] == "ag_1"
    assert payload["config_version"] == 2
    assert payload["changed_by"] == "u"


async def test_start_emits_status_changed(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, Any]]]],
) -> None:
    bus, calls = bus_spy
    after = _sample_record(status=AgentStatus.ACTIVE)
    repo = MagicMock()
    repo.update_status = AsyncMock(return_value=after)
    repo.get = AsyncMock(return_value=_sample_record())  # before: STOPPED
    svc = AgentRegistryService(repo, workspace_id="ws", event_bus=bus)

    await svc.start_agent("ag_1")

    names = [n for n, _ in calls]
    assert AGENT_STATUS_CHANGED in names
    payload = next(p for n, p in calls if n == AGENT_STATUS_CHANGED)
    assert payload["agent_id"] == "ag_1"
    assert payload["old_status"] == "stopped"
    assert payload["new_status"] == "active"


async def test_delete_emits_only_agent_deleted(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, Any]]]],
) -> None:
    """W5 rule: delete_agent emits ONLY AGENT_DELETED, not AGENT_STATUS_CHANGED."""
    bus, calls = bus_spy
    archived = _sample_record(status=AgentStatus.ARCHIVED)
    repo = MagicMock()
    repo.update_status = AsyncMock(return_value=archived)
    repo.get = AsyncMock(return_value=_sample_record())
    svc = AgentRegistryService(repo, workspace_id="ws", event_bus=bus)

    result = await svc.delete_agent("ag_1")
    assert result is True

    names = [n for n, _ in calls]
    assert AGENT_DELETED in names
    assert AGENT_STATUS_CHANGED not in names


async def test_delete_missing_agent_no_events(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, Any]]]],
) -> None:
    """Non-existent agent: no state change, no events emitted."""
    bus, calls = bus_spy
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    # update_status would never be called for a missing agent
    repo.update_status = AsyncMock(return_value=None)
    svc = AgentRegistryService(repo, workspace_id="ws", event_bus=bus)

    result = await svc.delete_agent("ag_missing")
    assert result is False
    assert calls == []


async def test_no_event_bus_no_error() -> None:
    """event_bus=None: methods complete without crashing, no emit attempts."""
    repo = MagicMock()
    repo.save_new = AsyncMock(return_value=_sample_record())
    svc = AgentRegistryService(repo, workspace_id="ws")  # event_bus defaults to None
    record = await svc.create_agent(name="one", model="m", created_by="u")
    assert record.id == "ag_1"
