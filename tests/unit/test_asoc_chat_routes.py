"""Unit tests for ASOC chat-history routes (MTRNIX-353, T3).

Uses FastAPI TestClient with dependency_overrides for ChatPersistence and auth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_chat_persistence
from metatron.api.routes.asoc_chat import router as asoc_chat_router
from metatron.auth.dependencies import get_current_user, require_editor, require_viewer
from metatron.chat.models import ChatMessage, ChatMessageRole, ChatThread
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import Settings
from metatron.core.models import Role, User

_WS = "ws-asoc-1"
_USER = "user-42"
_THREAD_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_MSG_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: Role = Role.VIEWER, workspace_ids: list[str] | None = None) -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=role,
        workspace_ids=workspace_ids or [_WS],
    )


def _sample_thread(**overrides: Any) -> ChatThread:
    base: dict[str, Any] = {
        "thread_id": _THREAD_ID,
        "workspace_id": _WS,
        "user_id": _USER,
        "created_at": _NOW,
        "last_message_at": None,
    }
    base.update(overrides)
    return ChatThread(**base)


def _sample_message(**overrides: Any) -> ChatMessage:
    base: dict[str, Any] = {
        "id": _MSG_ID,
        "thread_id": _THREAD_ID,
        "role": ChatMessageRole.USER,
        "content": "Hello ASOC",
        "citations_json": None,
        "tool_calls_json": None,
        "created_at": _NOW,
    }
    base.update(overrides)
    return ChatMessage(**base)


def _make_app(
    persistence: ChatPersistence,
    user: User | None = None,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    if user is None:
        user = _make_user()
    if settings is None:
        settings = Settings(METATRON_ENV="development", AUTH_ENABLED=False)

    app = FastAPI()
    app.state.settings = settings
    app.include_router(asoc_chat_router, prefix="/api/v1")

    # Override auth — require_viewer/require_editor return User in the actual implementation
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_viewer] = lambda: user
    app.dependency_overrides[require_editor] = lambda: user
    # Override chat persistence
    app.dependency_overrides[get_chat_persistence] = lambda: persistence

    # Inject workspace_id into request.state.user so get_workspace_id() resolves correctly.
    # In production this is done by OptionalAuthMiddleware; in tests we inject it manually.
    from fastapi import Request as _Request

    _ws_ids = user.workspace_ids  # capture for closure

    @app.middleware("http")
    async def inject_state(request: _Request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = {"workspace_ids": _ws_ids, "role": "viewer"}
        return await call_next(request)

    return app


# ===========================================================================
# GET /api/v1/chat/threads
# ===========================================================================


class TestListChatThreads:
    def test_returns_threads_list(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = [_sample_thread()]
        user = _make_user(workspace_ids=[_WS])
        app = _make_app(persistence, user)

        resp = TestClient(app).get(f"/api/v1/chat/threads?workspace_id={_WS}&user_id={_USER}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["threads"][0]["workspace_id"] == _WS
        assert data["threads"][0]["user_id"] == _USER

    def test_empty_list_when_no_threads(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)

        resp = TestClient(app).get(f"/api/v1/chat/threads?workspace_id={_WS}&user_id={_USER}")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_403_when_workspace_mismatch(self) -> None:
        """Caller authenticated for ws-A but requests ws-B."""
        persistence = AsyncMock(spec=ChatPersistence)
        user = _make_user(workspace_ids=["ws-A"])
        app = _make_app(persistence, user)

        resp = TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/chat/threads?workspace_id=ws-B&user_id=user-1"
        )

        assert resp.status_code == 403

    def test_missing_workspace_id_returns_422(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/chat/threads?user_id={_USER}"
        )

        assert resp.status_code == 422


# ===========================================================================
# GET /api/v1/chat/threads/{thread_id}/messages
# ===========================================================================


class TestListThreadMessages:
    def test_returns_messages(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _sample_thread()
        persistence.list_messages.return_value = [_sample_message()]
        app = _make_app(persistence)

        resp = TestClient(app).get(f"/api/v1/chat/threads/{_THREAD_ID}/messages")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["messages"][0]["content"] == "Hello ASOC"

    def test_404_when_thread_not_found(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = None
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/chat/threads/{_THREAD_ID}/messages"
        )

        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/chat/threads/not-a-uuid/messages"
        )

        assert resp.status_code == 400

    def test_workspace_scoped_from_auth(self) -> None:
        """Workspace passed to persistence.get_thread comes from auth, not query."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _sample_thread()
        persistence.list_messages.return_value = []
        app = _make_app(persistence)

        TestClient(app).get(f"/api/v1/chat/threads/{_THREAD_ID}/messages")

        # The workspace_id arg should match _WS (from auth)
        persistence.get_thread.assert_called_once_with(_WS, _THREAD_ID)


# ===========================================================================
# DELETE /api/v1/chat/threads/{thread_id}
# ===========================================================================


class TestDeleteChatThread:
    def test_204_on_success(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        user = _make_user(role=Role.EDITOR)
        app = _make_app(persistence, user)

        resp = TestClient(app).delete(f"/api/v1/chat/threads/{_THREAD_ID}")

        assert resp.status_code == 204

    def test_404_when_thread_not_found(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = False
        user = _make_user(role=Role.EDITOR)
        app = _make_app(persistence, user)

        resp = TestClient(app, raise_server_exceptions=False).delete(
            f"/api/v1/chat/threads/{_THREAD_ID}"
        )

        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        user = _make_user(role=Role.EDITOR)
        app = _make_app(persistence, user)

        resp = TestClient(app, raise_server_exceptions=False).delete(
            "/api/v1/chat/threads/not-a-uuid"
        )

        assert resp.status_code == 400

    def test_workspace_from_auth(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        user = _make_user(role=Role.EDITOR)
        app = _make_app(persistence, user)

        TestClient(app).delete(f"/api/v1/chat/threads/{_THREAD_ID}")

        persistence.delete_thread.assert_called_once_with(_WS, _THREAD_ID)
