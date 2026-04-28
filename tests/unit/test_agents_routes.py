"""Tests for /api/v1/agents routes.

Uses FastAPI TestClient with dependency overrides so the routes exercise the
full request/response stack without touching the DB. A final CRUD-cycle test
doubles as an integration test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.agents.models import AgentConfigVersion, AgentRecord, AgentStatus
from metatron.agents.service import (
    AgentInvalidStateTransitionError,
    AgentNameConflictError,
    AgentNotFoundError,
    AgentRegistryService,
)
from metatron.api.dependencies import get_agent_registry_service
from metatron.api.routes.agents import router as agents_router
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.models import Role, User

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        METATRON_SECRET_KEY="test-secret",
    )


def _make_user(role: Role = Role.EDITOR) -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=role,
        workspace_ids=["ws-test"],
    )


def _sample_record(**overrides: Any) -> AgentRecord:
    base: dict[str, Any] = {
        "id": "agent-1",
        "workspace_id": "ws-test",
        "name": "Trader",
        "status": AgentStatus.STOPPED,
        "model": "gpt-4",
        "capabilities": ["trade"],
        "tools": ["search"],
        "memory_bindings": {"per_agent": True},
        "budget": {"daily_usd": 5.0},
        "config_version": 1,
        "current_config": {
            "name": "Trader",
            "model": "gpt-4",
            "capabilities": ["trade"],
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
def service() -> AsyncMock:
    """AsyncMock AgentRegistryService for dependency override."""
    return AsyncMock(spec=AgentRegistryService)


@pytest.fixture
def make_client(
    settings: Settings,
    service: AsyncMock,
) -> Callable[..., TestClient]:
    def _factory(role: Role = Role.EDITOR) -> TestClient:
        app = FastAPI()
        app.state.settings = settings
        app.include_router(agents_router, prefix="/api/v1")
        app.dependency_overrides[get_agent_registry_service] = lambda: service
        app.dependency_overrides[get_current_user] = lambda: _make_user(role=role)
        return TestClient(app, raise_server_exceptions=False)

    return _factory


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client(Role.EDITOR)


# ---------------------------------------------------------------------------
# POST /agents
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_create_201(self, client: TestClient, service: AsyncMock) -> None:
        service.create_agent.return_value = _sample_record()
        response = client.post(
            "/api/v1/agents",
            json={
                "name": "Trader",
                "model": "gpt-4",
                "capabilities": ["trade"],
                "tools": ["search"],
                "memory_bindings": {"per_agent": True},
                "budget": {"daily_usd": 5.0},
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["id"] == "agent-1"
        assert body["status"] == "stopped"
        assert body["config_version"] == 1
        service.create_agent.assert_awaited_once()
        kwargs = service.create_agent.await_args.kwargs
        assert kwargs["name"] == "Trader"
        assert kwargs["created_by"] == "u1"

    def test_create_empty_name_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/agents",
            json={"name": "", "model": "gpt-4"},
        )
        assert response.status_code == 422

    def test_create_conflict_409(self, client: TestClient, service: AsyncMock) -> None:
        service.create_agent.side_effect = AgentNameConflictError("dup")
        response = client.post(
            "/api/v1/agents",
            json={"name": "Trader", "model": "gpt-4"},
        )
        assert response.status_code == 409

    def test_create_viewer_forbidden(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        viewer_client = make_client(Role.VIEWER)
        response = viewer_client.post(
            "/api/v1/agents",
            json={"name": "Trader", "model": "gpt-4"},
        )
        assert response.status_code == 403
        service.create_agent.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /agents
# ---------------------------------------------------------------------------


class TestListAgents:
    def test_list_200(self, client: TestClient, service: AsyncMock) -> None:
        service.list_agents.return_value = [_sample_record()]
        response = client.get("/api/v1/agents", params={"limit": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["limit"] == 10
        assert body["has_more"] is False
        kwargs = service.list_agents.await_args.kwargs
        assert kwargs["limit"] == 11  # has_more trick

    def test_list_has_more(self, client: TestClient, service: AsyncMock) -> None:
        service.list_agents.return_value = [
            _sample_record(id=f"a{i}", name=f"Trader-{i}") for i in range(3)
        ]
        response = client.get("/api/v1/agents", params={"limit": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["has_more"] is True

    def test_list_with_filters(self, client: TestClient, service: AsyncMock) -> None:
        service.list_agents.return_value = []
        response = client.get(
            "/api/v1/agents",
            params={"status": "active", "name_prefix": "Tra"},
        )
        assert response.status_code == 200
        kwargs = service.list_agents.await_args.kwargs
        assert kwargs["status"] == AgentStatus.ACTIVE
        assert kwargs["name_prefix"] == "Tra"

    # MTRNIX-324: default-exclude ARCHIVED + include_archived opt-in

    def test_list_default_excludes_archived(
        self, client: TestClient, service: AsyncMock
    ) -> None:
        """Default GET /agents passes include_archived=False to the service."""
        service.list_agents.return_value = []
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        kwargs = service.list_agents.await_args.kwargs
        assert kwargs["include_archived"] is False
        assert kwargs["status"] is None

    def test_list_include_archived_true(
        self, client: TestClient, service: AsyncMock
    ) -> None:
        """?include_archived=true forwards include_archived=True to the service."""
        service.list_agents.return_value = []
        response = client.get("/api/v1/agents", params={"include_archived": "true"})
        assert response.status_code == 200
        kwargs = service.list_agents.await_args.kwargs
        assert kwargs["include_archived"] is True
        assert kwargs["status"] is None

    def test_list_explicit_status_archived(
        self, client: TestClient, service: AsyncMock
    ) -> None:
        """?status=archived passes status=ARCHIVED through (archived-only view)."""
        service.list_agents.return_value = []
        response = client.get("/api/v1/agents", params={"status": "archived"})
        assert response.status_code == 200
        kwargs = service.list_agents.await_args.kwargs
        assert kwargs["status"] == AgentStatus.ARCHIVED
        assert kwargs["include_archived"] is False

    def test_list_status_and_include_archived_conflict_400(
        self, client: TestClient, service: AsyncMock
    ) -> None:
        """status + include_archived=true is mutually exclusive ⇒ 400."""
        response = client.get(
            "/api/v1/agents",
            params={"status": "active", "include_archived": "true"},
        )
        assert response.status_code == 400
        assert "mutually exclusive" in response.json()["detail"]
        service.list_agents.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /agents/{id}
# ---------------------------------------------------------------------------


class TestGetAgent:
    def test_get_200(self, client: TestClient, service: AsyncMock) -> None:
        service.get_agent.return_value = _sample_record()
        response = client.get("/api/v1/agents/agent-1")
        assert response.status_code == 200
        assert response.json()["id"] == "agent-1"

    def test_get_404(self, client: TestClient, service: AsyncMock) -> None:
        service.get_agent.side_effect = AgentNotFoundError("nope")
        response = client.get("/api/v1/agents/missing")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /agents/{id}
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    def test_update_200(self, client: TestClient, service: AsyncMock) -> None:
        updated = _sample_record(name="TraderV2", config_version=2)
        service.update_agent.return_value = updated
        response = client.put(
            "/api/v1/agents/agent-1",
            json={"name": "TraderV2"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "TraderV2"
        assert body["config_version"] == 2
        kwargs = service.update_agent.await_args.kwargs
        assert kwargs["name"] == "TraderV2"
        assert kwargs["changed_by"] == "u1"

    def test_update_empty_body_422(self, client: TestClient) -> None:
        response = client.put("/api/v1/agents/agent-1", json={})
        assert response.status_code == 422

    def test_update_404(self, client: TestClient, service: AsyncMock) -> None:
        service.update_agent.side_effect = AgentNotFoundError("nope")
        response = client.put(
            "/api/v1/agents/missing",
            json={"name": "X"},
        )
        assert response.status_code == 404

    def test_update_conflict_409(self, client: TestClient, service: AsyncMock) -> None:
        service.update_agent.side_effect = AgentNameConflictError("dup")
        response = client.put(
            "/api/v1/agents/agent-1",
            json={"name": "Taken"},
        )
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /agents/{id}
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    def test_delete_204(self, client: TestClient, service: AsyncMock) -> None:
        service.delete_agent.return_value = True
        response = client.delete("/api/v1/agents/agent-1")
        assert response.status_code == 204
        assert response.content == b""

    def test_delete_404(self, client: TestClient, service: AsyncMock) -> None:
        service.delete_agent.return_value = False
        response = client.delete("/api/v1/agents/missing")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_200(self, client: TestClient, service: AsyncMock) -> None:
        service.start_agent.return_value = _sample_record(status=AgentStatus.ACTIVE)
        response = client.post("/api/v1/agents/agent-1/start")
        assert response.status_code == 200
        assert response.json()["status"] == "active"

    def test_stop_200(self, client: TestClient, service: AsyncMock) -> None:
        service.stop_agent.return_value = _sample_record(status=AgentStatus.STOPPED)
        response = client.post("/api/v1/agents/agent-1/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"

    def test_pause_200(self, client: TestClient, service: AsyncMock) -> None:
        service.pause_agent.return_value = _sample_record(status=AgentStatus.PAUSED)
        response = client.post("/api/v1/agents/agent-1/pause")
        assert response.status_code == 200
        assert response.json()["status"] == "paused"

    def test_start_404(self, client: TestClient, service: AsyncMock) -> None:
        service.start_agent.side_effect = AgentNotFoundError("nope")
        response = client.post("/api/v1/agents/missing/start")
        assert response.status_code == 404

    def test_viewer_cannot_start(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        viewer_client = make_client(Role.VIEWER)
        response = viewer_client.post("/api/v1/agents/agent-1/start")
        assert response.status_code == 403
        service.start_agent.assert_not_awaited()

    def test_start_archived_returns_400(self, client: TestClient, service: AsyncMock) -> None:
        """Service rejects start from ARCHIVED → route maps to 400."""
        service.start_agent.side_effect = AgentInvalidStateTransitionError(
            "transition to 'active' not allowed from 'archived'"
        )
        response = client.post("/api/v1/agents/agent-1/start")
        assert response.status_code == 400
        assert "archived" in response.json()["detail"]

    def test_stop_archived_returns_400(self, client: TestClient, service: AsyncMock) -> None:
        service.stop_agent.side_effect = AgentInvalidStateTransitionError(
            "transition to 'stopped' not allowed from 'archived'"
        )
        response = client.post("/api/v1/agents/agent-1/stop")
        assert response.status_code == 400

    def test_pause_archived_returns_400(self, client: TestClient, service: AsyncMock) -> None:
        service.pause_agent.side_effect = AgentInvalidStateTransitionError(
            "transition to 'paused' not allowed from 'archived'"
        )
        response = client.post("/api/v1/agents/agent-1/pause")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Restore — ARCHIVED → STOPPED
# ---------------------------------------------------------------------------


class TestRestore:
    def test_restore_200_from_archived(self, client: TestClient, service: AsyncMock) -> None:
        service.restore_agent.return_value = _sample_record(status=AgentStatus.STOPPED)
        response = client.post("/api/v1/agents/agent-1/restore")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"
        service.restore_agent.assert_awaited_once_with("agent-1")

    def test_restore_400_when_not_archived(self, client: TestClient, service: AsyncMock) -> None:
        service.restore_agent.side_effect = AgentInvalidStateTransitionError(
            "restore requires source state 'archived', got 'active'"
        )
        response = client.post("/api/v1/agents/agent-1/restore")
        assert response.status_code == 400

    def test_restore_404_missing(self, client: TestClient, service: AsyncMock) -> None:
        service.restore_agent.side_effect = AgentNotFoundError("nope")
        response = client.post("/api/v1/agents/missing/restore")
        assert response.status_code == 404

    def test_restore_409_when_name_collides(self, client: TestClient, service: AsyncMock) -> None:
        service.restore_agent.side_effect = AgentNameConflictError(
            "agent name already exists in workspace"
        )
        response = client.post("/api/v1/agents/agent-1/restore")
        assert response.status_code == 409

    def test_restore_viewer_forbidden_403(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        viewer_client = make_client(Role.VIEWER)
        response = viewer_client.post("/api/v1/agents/agent-1/restore")
        assert response.status_code == 403
        service.restore_agent.assert_not_awaited()


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


class TestVersions:
    def test_versions_200(self, client: TestClient, service: AsyncMock) -> None:
        service.list_versions.return_value = [
            AgentConfigVersion(
                agent_id="agent-1",
                version=2,
                config={"name": "TraderV2"},
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
        response = client.get("/api/v1/agents/agent-1/versions")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["versions"][0]["version"] == 2
        assert body["has_more"] is False
        kwargs = service.list_versions.await_args.kwargs
        assert kwargs["limit"] == 51

    def test_versions_404(self, client: TestClient, service: AsyncMock) -> None:
        service.list_versions.side_effect = AgentNotFoundError("nope")
        response = client.get("/api/v1/agents/missing/versions")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Full CRUD cycle (integration-style)
# ---------------------------------------------------------------------------


class TestAgentCRUDCycle:
    def test_create_list_get_update_start_delete(
        self, client: TestClient, service: AsyncMock
    ) -> None:
        stored = _sample_record(id="cycle-1")
        service.create_agent.return_value = stored
        service.list_agents.return_value = [stored]
        service.get_agent.return_value = stored
        service.update_agent.return_value = _sample_record(
            id="cycle-1", name="Renamed", config_version=2
        )
        service.start_agent.return_value = _sample_record(id="cycle-1", status=AgentStatus.ACTIVE)
        service.delete_agent.return_value = True

        # CREATE
        create = client.post(
            "/api/v1/agents",
            json={"name": "Trader", "model": "gpt-4"},
        )
        assert create.status_code == 201
        assert create.json()["id"] == "cycle-1"

        # LIST
        listing = client.get("/api/v1/agents")
        assert listing.status_code == 200
        assert listing.json()["count"] == 1

        # GET
        fetched = client.get("/api/v1/agents/cycle-1")
        assert fetched.status_code == 200

        # UPDATE
        put = client.put(
            "/api/v1/agents/cycle-1",
            json={"name": "Renamed"},
        )
        assert put.status_code == 200
        assert put.json()["name"] == "Renamed"

        # START
        started = client.post("/api/v1/agents/cycle-1/start")
        assert started.status_code == 200
        assert started.json()["status"] == "active"

        # DELETE
        deleted = client.delete("/api/v1/agents/cycle-1")
        assert deleted.status_code == 204
        service.delete_agent.assert_awaited_once()


# ---------------------------------------------------------------------------
# Audit fields (created_by / changed_by wiring from authenticated user)
# ---------------------------------------------------------------------------


class TestAuditFields:
    def test_created_by_taken_from_auth_user(self, client: TestClient, service: AsyncMock) -> None:
        service.create_agent.return_value = _sample_record()
        client.post(
            "/api/v1/agents",
            json={"name": "Trader", "model": "gpt-4"},
        )
        kwargs = service.create_agent.await_args.kwargs
        assert kwargs["created_by"] == "u1"

    def test_changed_by_taken_from_auth_user(self, client: TestClient, service: AsyncMock) -> None:
        service.update_agent.return_value = _sample_record(config_version=2)
        client.put(
            "/api/v1/agents/agent-1",
            json={"name": "X"},
        )
        kwargs = service.update_agent.await_args.kwargs
        assert kwargs["changed_by"] == "u1"
