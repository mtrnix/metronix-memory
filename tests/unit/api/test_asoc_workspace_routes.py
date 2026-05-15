"""Unit tests for ASOC workspace lifecycle routes (MTRNIX-352, T2).

Uses a minimal FastAPI test app with dependency overrides.  Tests cover:
- 200/202 on bootstrap (idempotent + new)
- 404 on missing workspace
- 409 on invalid transition
- 204 on delete (idempotent)
- GET /status 200/404
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.routes.asoc_workspace import router
from metatron.auth.dependencies import get_current_user
from metatron.core.exceptions import WorkspaceNotFoundError, WorkspaceStateTransitionError
from metatron.core.models import Role, User
from metatron.workspaces.bootstrap.models import BootstrapState, BootstrapStateEnum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: Role = Role.ADMIN) -> User:
    return User(
        id="u1",
        username="admin",
        email="admin@example.com",
        role=role,
        workspace_ids=["*"],
    )


def _make_state(
    workspace_id: str = "ws-test",
    state: BootstrapStateEnum = BootstrapStateEnum.BOOTSTRAPPING,
    **kwargs: Any,
) -> BootstrapState:
    defaults: dict[str, Any] = dict(
        workspace_id=workspace_id,
        state=state,
        progress=0.0,
        current_step=None,
        last_processed_resource=None,
        last_processed_id=None,
        indexed_count=0,
        total_count=None,
        last_error=None,
        last_synced_at=None,
        retry_count=0,
        next_retry_at=None,
        updated_at=datetime(2026, 5, 15, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return BootstrapState(**defaults)


def _make_app(
    mgr: Any = None,
    store: Any = None,
    user_role: Role = Role.ADMIN,
) -> TestClient:
    """Build a minimal FastAPI test app.

    The DI helpers _get_workspace_manager and _get_bootstrap_store read from
    ``app.state``, so we set the attributes directly rather than relying on
    ``dependency_overrides`` (which only works for FastAPI Depends() callables).
    """
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _make_user(user_role)
    # Wire state attributes — the DI helpers read these via request.app.state.
    app.state.workspace_manager_async = mgr if mgr is not None else MagicMock()
    app.state.bootstrap_state_store = store if store is not None else MagicMock()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /workspace/bootstrap
# ---------------------------------------------------------------------------


class TestBootstrapEndpoint:
    def test_new_workspace_returns_200(self) -> None:
        """New workspace: store returns None (absent) → bootstrap creates it."""
        store = AsyncMock()
        store.get.return_value = None  # absent
        mgr = AsyncMock()
        state = _make_state(state=BootstrapStateEnum.BOOTSTRAPPING)
        mgr.bootstrap.return_value = state

        client = _make_app(mgr=mgr, store=store)
        resp = client.post(
            "/api/v1/workspace/bootstrap",
            json={
                "workspace_id": "ws-test",
                "source": "asoc",
                "config": {
                    "url": "http://asoc",
                    "service_token": "tok",
                    "project_id": "p1",
                    "asoc_instance_id": "i1",
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace_id"] == "ws-test"
        assert body["state"] == "bootstrapping"

    def test_existing_workspace_is_idempotent(self) -> None:
        """Existing workspace → 200 with current state."""
        store = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.READY)
        mgr = AsyncMock()
        mgr.bootstrap.return_value = _make_state(state=BootstrapStateEnum.READY)

        client = _make_app(mgr=mgr, store=store)
        resp = client.post(
            "/api/v1/workspace/bootstrap",
            json={
                "workspace_id": "ws-test",
                "source": "asoc",
                "config": {
                    "url": "http://asoc",
                    "service_token": "tok",
                    "project_id": "p1",
                    "asoc_instance_id": "i1",
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "ready"

    def test_archived_returns_409(self) -> None:
        """Archived workspace → 409 Conflict."""
        store = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.ARCHIVED)
        mgr = AsyncMock()
        mgr.bootstrap.side_effect = WorkspaceStateTransitionError(
            "Workspace is archived"
        )

        client = _make_app(mgr=mgr, store=store)
        resp = client.post(
            "/api/v1/workspace/bootstrap",
            json={
                "workspace_id": "ws-test",
                "source": "asoc",
                "config": {
                    "url": "http://asoc",
                    "service_token": "tok",
                    "project_id": "p1",
                    "asoc_instance_id": "i1",
                },
            },
        )
        assert resp.status_code == 409

    def test_invalid_workspace_id_pattern_returns_422(self) -> None:
        """workspace_id with special chars rejected by Pydantic."""
        client = _make_app()
        resp = client.post(
            "/api/v1/workspace/bootstrap",
            json={
                "workspace_id": "ws with spaces!",
                "source": "asoc",
                "config": {
                    "url": "http://asoc",
                    "service_token": "tok",
                    "project_id": "p1",
                    "asoc_instance_id": "i1",
                },
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /workspace/{workspace_id}/archive
# ---------------------------------------------------------------------------


class TestArchiveEndpoint:
    def test_archive_ready_returns_200(self) -> None:
        mgr = AsyncMock()
        mgr.archive.return_value = _make_state(state=BootstrapStateEnum.ARCHIVED)
        client = _make_app(mgr=mgr)
        resp = client.post("/api/v1/workspace/ws-test/archive")
        assert resp.status_code == 200
        assert resp.json()["state"] == "archived"

    def test_archive_missing_returns_404(self) -> None:
        mgr = AsyncMock()
        mgr.archive.side_effect = WorkspaceNotFoundError("ws-missing")
        client = _make_app(mgr=mgr)
        resp = client.post("/api/v1/workspace/ws-missing/archive")
        assert resp.status_code == 404

    def test_archive_invalid_transition_returns_409(self) -> None:
        mgr = AsyncMock()
        mgr.archive.side_effect = WorkspaceStateTransitionError("bad state")
        client = _make_app(mgr=mgr)
        resp = client.post("/api/v1/workspace/ws-test/archive")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /workspace/{workspace_id}/unarchive
# ---------------------------------------------------------------------------


class TestUnarchiveEndpoint:
    def test_unarchive_archived_returns_200(self) -> None:
        mgr = AsyncMock()
        mgr.unarchive.return_value = _make_state(state=BootstrapStateEnum.READY)
        client = _make_app(mgr=mgr)
        resp = client.post("/api/v1/workspace/ws-test/unarchive")
        assert resp.status_code == 200
        assert resp.json()["state"] == "ready"

    def test_unarchive_missing_returns_404(self) -> None:
        mgr = AsyncMock()
        mgr.unarchive.side_effect = WorkspaceNotFoundError("ws-missing")
        client = _make_app(mgr=mgr)
        resp = client.post("/api/v1/workspace/ws-missing/unarchive")
        assert resp.status_code == 404

    def test_unarchive_wrong_state_returns_409(self) -> None:
        mgr = AsyncMock()
        mgr.unarchive.side_effect = WorkspaceStateTransitionError("not archived")
        client = _make_app(mgr=mgr)
        resp = client.post("/api/v1/workspace/ws-test/unarchive")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /workspace/{workspace_id}
# ---------------------------------------------------------------------------


class TestDeleteEndpoint:
    def test_delete_returns_204(self) -> None:
        mgr = AsyncMock()
        mgr.delete.return_value = True
        client = _make_app(mgr=mgr)
        resp = client.delete("/api/v1/workspace/ws-test")
        assert resp.status_code == 204

    def test_delete_missing_workspace_still_204(self) -> None:
        """Delete is idempotent — absent workspace returns 204."""
        mgr = AsyncMock()
        mgr.delete.return_value = False  # nothing found
        client = _make_app(mgr=mgr)
        resp = client.delete("/api/v1/workspace/ws-missing")
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# GET /workspace/{workspace_id}/status
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    def test_status_returns_200_with_state(self) -> None:
        store = AsyncMock()
        store.get.return_value = _make_state(state=BootstrapStateEnum.READY)
        client = _make_app(store=store)
        resp = client.get("/api/v1/workspace/ws-test/status")
        assert resp.status_code == 200
        assert resp.json()["state"] == "ready"

    def test_status_missing_returns_404(self) -> None:
        store = AsyncMock()
        store.get.return_value = None
        client = _make_app(store=store)
        resp = client.get("/api/v1/workspace/ws-missing/status")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# RBAC — non-admin returns 403
# ---------------------------------------------------------------------------


class TestRbac:
    def test_bootstrap_requires_admin(self) -> None:
        client = _make_app(user_role=Role.VIEWER)
        resp = client.post(
            "/api/v1/workspace/bootstrap",
            json={
                "workspace_id": "ws-test",
                "source": "asoc",
                "config": {
                    "url": "http://asoc",
                    "service_token": "tok",
                    "project_id": "p1",
                    "asoc_instance_id": "i1",
                },
            },
        )
        assert resp.status_code == 403

    def test_delete_requires_admin(self) -> None:
        client = _make_app(user_role=Role.EDITOR)
        resp = client.delete("/api/v1/workspace/ws-test")
        assert resp.status_code == 403
