"""Tests for GET /api/v1/agents/{agent_id}/memory/health (MTRNIX-277)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.agents.models import AgentRecord, AgentStatus
from metatron.agents.service import AgentNotFoundError, AgentRegistryService
from metatron.api.dependencies import get_agent_registry_service, get_memory_health_service
from metatron.api.routes.agents import router as agents_router
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.models import Role, User
from metatron.memory.health import AgentMemoryHealth, GrowthBucket, MemoryHealthService

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(METATRON_ENV="development", AUTH_ENABLED=False)


def _make_user(role: Role = Role.EDITOR) -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=role,
        workspace_ids=["ws-test"],
    )


def _sample_agent(**overrides: Any) -> AgentRecord:
    base: dict[str, Any] = {
        "id": "agent-1",
        "workspace_id": "ws-test",
        "name": "Trader",
        "status": AgentStatus.STOPPED,
        "model": "gpt-4",
        "capabilities": [],
        "tools": [],
        "memory_bindings": {},
        "budget": {},
        "config_version": 1,
        "current_config": {},
        "created_by": "u1",
        "created_at": datetime(2026, 5, 6, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 6, tzinfo=UTC),
    }
    base.update(overrides)
    return AgentRecord(**base)


def _sample_health(agent_id: str = "agent-1") -> AgentMemoryHealth:
    today = datetime.now(UTC).date()
    return AgentMemoryHealth(
        agent_id=agent_id,
        total_records=42,
        total_archived=5,
        growth_rate_per_day=1.5,
        growth_timeseries=[GrowthBucket(day=today, created_count=3)],
        unused_records=10,
        unused_threshold_days=30,
        duplicate_ratio=0.05,
        duplicate_clusters_count=2,
        duplicate_hamming_threshold=3,
        source_distribution={"chat": 30, "api": 12},
        computed_at=datetime.now(UTC),
    )


@pytest.fixture
def reg_service() -> AsyncMock:
    svc = AsyncMock(spec=AgentRegistryService)
    svc.workspace_id = "ws-test"
    return svc


@pytest.fixture
def health_service() -> AsyncMock:
    return AsyncMock(spec=MemoryHealthService)


@pytest.fixture
def make_client(
    settings: Settings,
    reg_service: AsyncMock,
    health_service: AsyncMock,
) -> Callable[..., TestClient]:
    def _factory(role: Role = Role.VIEWER) -> TestClient:
        app = FastAPI()
        app.state.settings = settings
        app.include_router(agents_router, prefix="/api/v1")
        app.dependency_overrides[get_agent_registry_service] = lambda: reg_service
        app.dependency_overrides[get_memory_health_service] = lambda: health_service
        app.dependency_overrides[get_current_user] = lambda: _make_user(role=role)
        return TestClient(app, raise_server_exceptions=False)

    return _factory


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGetAgentMemoryHealthHappyPath:
    def test_returns_200_with_correct_shape(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        agent = _sample_agent()
        reg_service.get_agent = AsyncMock(return_value=agent)
        health_service.compute = AsyncMock(return_value=_sample_health())

        client = make_client(role=Role.VIEWER)
        resp = client.get("/api/v1/agents/agent-1/memory/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-1"
        assert data["total_records"] == 42
        assert data["total_archived"] == 5
        assert data["unused_records"] == 10
        assert data["unused_threshold_days"] == 30
        assert abs(data["duplicate_ratio"] - 0.05) < 1e-9
        assert data["duplicate_clusters_count"] == 2
        assert data["duplicate_hamming_threshold"] == 3
        assert data["source_distribution"] == {"chat": 30, "api": 12}
        assert len(data["growth_timeseries"]) == 1
        assert "computed_at" in data
        # New fields disambiguate "skipped due to size" from "no duplicates".
        assert data["duplicate_detection_skipped"] is False
        assert data["duplicate_active_population"] == 0  # _sample_health default

    def test_growth_timeseries_item_has_day_and_count(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        agent = _sample_agent()
        reg_service.get_agent = AsyncMock(return_value=agent)
        today = datetime.now(UTC).date()
        health = AgentMemoryHealth(
            agent_id="agent-1",
            total_records=0,
            total_archived=0,
            growth_rate_per_day=0.0,
            growth_timeseries=[GrowthBucket(day=today, created_count=7)],
            unused_records=0,
            unused_threshold_days=30,
            duplicate_ratio=0.0,
            duplicate_clusters_count=0,
            duplicate_hamming_threshold=3,
            source_distribution={},
            computed_at=datetime.now(UTC),
        )
        health_service.compute = AsyncMock(return_value=health)

        client = make_client(role=Role.VIEWER)
        resp = client.get("/api/v1/agents/agent-1/memory/health")
        data = resp.json()
        bucket = data["growth_timeseries"][0]
        assert bucket["day"] == today.isoformat()
        assert bucket["created_count"] == 7


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


class TestRBAC:
    def test_viewer_is_accepted(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        reg_service.get_agent = AsyncMock(return_value=_sample_agent())
        health_service.compute = AsyncMock(return_value=_sample_health())
        client = make_client(role=Role.VIEWER)
        resp = client.get("/api/v1/agents/agent-1/memory/health")
        assert resp.status_code == 200

    def test_editor_is_accepted(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        reg_service.get_agent = AsyncMock(return_value=_sample_agent())
        health_service.compute = AsyncMock(return_value=_sample_health())
        client = make_client(role=Role.EDITOR)
        resp = client.get("/api/v1/agents/agent-1/memory/health")
        assert resp.status_code == 200

    def test_anonymous_denied(
        self,
        settings: Settings,
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        """Without a ``get_current_user`` override the route returns 401.

        ``require_viewer`` chains through ``Depends(get_current_user)``; with
        no override and no auth middleware mounted, FastAPI cannot resolve a
        user → ``HTTPException(401)``. Other test methods supply a user via
        ``app.dependency_overrides[get_current_user]`` and reach the route
        body. This test confirms the auth gate is real (not just decorative).
        """
        app = FastAPI()
        app.state.settings = settings
        app.include_router(agents_router, prefix="/api/v1")
        app.dependency_overrides[get_agent_registry_service] = lambda: reg_service
        app.dependency_overrides[get_memory_health_service] = lambda: health_service
        # Intentionally no get_current_user override.
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/agents/agent-1/memory/health")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Not-found / cross-workspace
# ---------------------------------------------------------------------------


class TestNotFound:
    def test_returns_404_for_unknown_agent(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        reg_service.get_agent = AsyncMock(
            side_effect=AgentNotFoundError("agent not found: 'unknown'")
        )
        client = make_client(role=Role.VIEWER)
        resp = client.get("/api/v1/agents/unknown/memory/health")
        assert resp.status_code == 404

    def test_returns_404_for_cross_workspace_agent(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        # Agent exists but belongs to a different workspace.
        agent = _sample_agent(workspace_id="ws-other")
        reg_service.get_agent = AsyncMock(return_value=agent)
        reg_service.workspace_id = "ws-test"  # current workspace

        client = make_client(role=Role.VIEWER)
        resp = client.get("/api/v1/agents/agent-1/memory/health")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Empty agent (zero records)
# ---------------------------------------------------------------------------


class TestEmptyAgent:
    def test_returns_zeros_for_new_agent(
        self,
        make_client: Callable[..., TestClient],
        reg_service: AsyncMock,
        health_service: AsyncMock,
    ) -> None:
        agent = _sample_agent()
        reg_service.get_agent = AsyncMock(return_value=agent)

        empty_health = AgentMemoryHealth(
            agent_id="agent-1",
            total_records=0,
            total_archived=0,
            growth_rate_per_day=0.0,
            growth_timeseries=[],
            unused_records=0,
            unused_threshold_days=30,
            duplicate_ratio=0.0,
            duplicate_clusters_count=0,
            duplicate_hamming_threshold=3,
            source_distribution={},
            computed_at=datetime.now(UTC),
        )
        health_service.compute = AsyncMock(return_value=empty_health)

        client = make_client(role=Role.VIEWER)
        resp = client.get("/api/v1/agents/agent-1/memory/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_records"] == 0
        assert data["growth_timeseries"] == []
        assert data["source_distribution"] == {}
