"""Unit tests for AgentRegistryService.

Uses AsyncMock for the AgentPersistence repo so the service's workspace-binding
and merge/snapshot semantics are exercised in isolation from the DB layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from metatron.agents.models import AgentConfigVersion, AgentRecord, AgentStatus
from metatron.agents.persistence import _AgentNameConflictError as PersistenceNameConflict
from metatron.agents.service import (
    AgentNameConflictError,
    AgentNotFoundError,
    AgentRegistryService,
)


def _sample_record(**overrides: Any) -> AgentRecord:
    base: dict[str, Any] = {
        "id": "agent-1",
        "workspace_id": "ws-test",
        "name": "Trader",
        "status": AgentStatus.STOPPED,
        "model": "gpt-4",
        "capabilities": ["research", "trade"],
        "tools": ["search"],
        "memory_bindings": {"per_agent": True},
        "budget": {"daily_usd": 5.0},
        "config_version": 1,
        "current_config": {
            "name": "Trader",
            "model": "gpt-4",
            "capabilities": ["research", "trade"],
            "tools": ["search"],
            "memory_bindings": {"per_agent": True},
            "budget": {"daily_usd": 5.0},
        },
        "created_by": "u1",
        "created_at": datetime(2026, 4, 21, tzinfo=UTC),
        "updated_at": datetime(2026, 4, 21, tzinfo=UTC),
    }
    base.update(overrides)
    return AgentRecord(**base)


@pytest.fixture
def repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(repo: AsyncMock) -> AgentRegistryService:
    return AgentRegistryService(repo, workspace_id="ws-test")


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


class TestCreateAgent:
    async def test_creates_stopped_v1(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.save_new.side_effect = lambda r: r

        record = await service.create_agent(
            name="Trader",
            model="gpt-4",
            capabilities=["trade"],
            tools=["search"],
            memory_bindings={"per_agent": True},
            budget={"daily_usd": 5.0},
            created_by="u1",
        )

        assert record.status == AgentStatus.STOPPED
        assert record.config_version == 1
        assert record.workspace_id == "ws-test"
        assert record.created_by == "u1"
        assert record.current_config == {
            "name": "Trader",
            "model": "gpt-4",
            "capabilities": ["trade"],
            "tools": ["search"],
            "memory_bindings": {"per_agent": True},
            "budget": {"daily_usd": 5.0},
        }
        repo.save_new.assert_awaited_once()

    async def test_defaults_for_optional_payload(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.save_new.side_effect = lambda r: r
        record = await service.create_agent(
            name="Bare",
            model="gpt-4",
            created_by="u1",
        )
        assert record.capabilities == []
        assert record.tools == []
        assert record.memory_bindings == {}
        assert record.budget == {}
        assert record.current_config["capabilities"] == []

    async def test_name_conflict(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.save_new.side_effect = PersistenceNameConflict("dup")
        with pytest.raises(AgentNameConflictError):
            await service.create_agent(
                name="Trader",
                model="gpt-4",
                created_by="u1",
            )


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


class TestGetAgent:
    async def test_found(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.get.return_value = _sample_record()
        record = await service.get_agent("agent-1")
        assert record.id == "agent-1"
        repo.get.assert_awaited_once_with("ws-test", "agent-1")

    async def test_missing_raises_not_found(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.get.return_value = None
        with pytest.raises(AgentNotFoundError):
            await service.get_agent("nope")


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    async def test_partial_merge_bumps_version(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        existing = _sample_record()
        repo.get.return_value = existing
        updated = _sample_record(
            name="TraderV2",
            config_version=2,
            current_config={
                "name": "TraderV2",
                "model": "gpt-4",
                "capabilities": ["research", "trade"],
                "tools": ["search"],
                "memory_bindings": {"per_agent": True},
                "budget": {"daily_usd": 5.0},
            },
        )
        repo.update_with_version_bump.return_value = updated

        result = await service.update_agent(
            "agent-1",
            name="TraderV2",
            changed_by="u2",
        )

        assert result.name == "TraderV2"
        assert result.config_version == 2

        _, kwargs = repo.update_with_version_bump.call_args
        assert kwargs["changed_by"] == "u2"
        nf = kwargs["new_fields"]
        # Unset fields retain their old values
        assert nf["name"] == "TraderV2"
        assert nf["model"] == "gpt-4"
        assert nf["capabilities"] == ["research", "trade"]
        # Snapshot mirrors merged payload
        assert nf["current_config"]["name"] == "TraderV2"

    async def test_empty_update_only_bumps_version(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        """Service itself does not block empty-payload updates; routes do via schema."""
        existing = _sample_record()
        repo.get.return_value = existing
        bumped = _sample_record(config_version=2)
        repo.update_with_version_bump.return_value = bumped

        result = await service.update_agent("agent-1", changed_by="u2")

        assert result.config_version == 2
        _, kwargs = repo.update_with_version_bump.call_args
        nf = kwargs["new_fields"]
        assert nf["name"] == existing.name
        assert nf["model"] == existing.model

    async def test_not_found_raises(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.get.return_value = None
        with pytest.raises(AgentNotFoundError):
            await service.update_agent("nope", name="x", changed_by="u2")

    async def test_name_conflict(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.get.return_value = _sample_record()
        repo.update_with_version_bump.side_effect = PersistenceNameConflict("dup")
        with pytest.raises(AgentNameConflictError):
            await service.update_agent("agent-1", name="dup", changed_by="u2")

    async def test_race_disappearance_raises_not_found(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.get.return_value = _sample_record()
        repo.update_with_version_bump.return_value = None
        with pytest.raises(AgentNotFoundError):
            await service.update_agent("agent-1", name="x", changed_by="u2")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_start_sets_active(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.update_status.return_value = _sample_record(status=AgentStatus.ACTIVE)
        result = await service.start_agent("agent-1")
        assert result.status == AgentStatus.ACTIVE
        repo.update_status.assert_awaited_once_with("ws-test", "agent-1", AgentStatus.ACTIVE)

    async def test_stop_sets_stopped(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.update_status.return_value = _sample_record(status=AgentStatus.STOPPED)
        result = await service.stop_agent("agent-1")
        assert result.status == AgentStatus.STOPPED

    async def test_pause_sets_paused(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.update_status.return_value = _sample_record(status=AgentStatus.PAUSED)
        result = await service.pause_agent("agent-1")
        assert result.status == AgentStatus.PAUSED

    async def test_start_missing_raises(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.update_status.return_value = None
        with pytest.raises(AgentNotFoundError):
            await service.start_agent("nope")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_soft_delete_archives(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.update_status.return_value = _sample_record(status=AgentStatus.ARCHIVED)
        result = await service.delete_agent("agent-1")
        assert result is True
        repo.update_status.assert_awaited_once_with("ws-test", "agent-1", AgentStatus.ARCHIVED)

    async def test_delete_missing_returns_false(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.update_status.return_value = None
        result = await service.delete_agent("missing")
        assert result is False


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:
    async def test_forwards_filters(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.list_records.return_value = [_sample_record()]
        records = await service.list_agents(
            status=AgentStatus.ACTIVE,
            name_prefix="Trad",
            limit=10,
            offset=5,
        )
        assert len(records) == 1
        repo.list_records.assert_awaited_once_with(
            "ws-test",
            status=AgentStatus.ACTIVE,
            name_prefix="Trad",
            limit=10,
            offset=5,
        )

    async def test_defaults(self, service: AgentRegistryService, repo: AsyncMock) -> None:
        repo.list_records.return_value = []
        records = await service.list_agents()
        assert records == []
        _, kwargs = repo.list_records.call_args
        assert kwargs["status"] is None
        assert kwargs["name_prefix"] is None
        assert kwargs["limit"] == 50
        assert kwargs["offset"] == 0


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


class TestVersions:
    async def test_list_versions_pre_checks_agent(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.get.return_value = _sample_record()
        repo.list_versions.return_value = [
            AgentConfigVersion(
                agent_id="agent-1",
                version=2,
                config={"name": "Trader"},
                changed_by="u2",
                changed_at=datetime(2026, 4, 21, tzinfo=UTC),
            ),
            AgentConfigVersion(
                agent_id="agent-1",
                version=1,
                config={"name": "Trader"},
                changed_by="u1",
                changed_at=datetime(2026, 4, 21, tzinfo=UTC),
            ),
        ]

        versions = await service.list_versions("agent-1", limit=10, offset=0)
        assert len(versions) == 2
        assert versions[0].version == 2
        repo.get.assert_awaited_once_with("ws-test", "agent-1")
        repo.list_versions.assert_awaited_once_with("ws-test", "agent-1", limit=10, offset=0)

    async def test_list_versions_unknown_agent_raises(
        self, service: AgentRegistryService, repo: AsyncMock
    ) -> None:
        repo.get.return_value = None
        with pytest.raises(AgentNotFoundError):
            await service.list_versions("nope")
        repo.list_versions.assert_not_awaited()
