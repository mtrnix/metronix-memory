"""Unit tests for ASOC chat-history routes (MTRNIX-353, T3 + MTRNIX-354, T4 auth).

Uses FastAPI TestClient with dependency overrides for ChatPersistence and asoc_auth.
Auth was swapped from require_viewer/require_editor to asoc_auth in T4.
The workspace is now derived from the JWT project_id (not from query params).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import jwt as pyjwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_chat_persistence
from metatron.api.routes.asoc_chat import router as asoc_chat_router
from metatron.chat.models import ChatMessage, ChatMessageRole, ChatThread
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import Settings

_SECRET = "test-secret-for-t3-tests"
_ALGO = "HS256"
_INSTANCE = "pilot"
_PROJECT_ID = "proj-t3"
_USER_ID = "user-t3"
_THREAD_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_MSG_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
_WS = f"asoc-{_INSTANCE}-{_PROJECT_ID}"


def _make_jwt() -> str:
    return pyjwt.encode(
        {
            "sub": _USER_ID,
            "project_id": _PROJECT_ID,
            "exp": int(time.time()) + 3600,
        },
        _SECRET,
        algorithm=_ALGO,
    )


def _sample_thread(**overrides: Any) -> ChatThread:
    base: dict[str, Any] = {
        "thread_id": _THREAD_ID,
        "workspace_id": _WS,
        "user_id": _USER_ID,
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
    *,
    settings: Settings | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings(
            ASOC_SHARED_SECRET=_SECRET,
            ASOC_JWT_ALGORITHM=_ALGO,
            METATRON_ASOC_INSTANCE_ID=_INSTANCE,
        )

    app = FastAPI()
    app.state.settings = settings
    app.include_router(asoc_chat_router, prefix="/api/v1/asoc")
    app.dependency_overrides[get_chat_persistence] = lambda: persistence
    return app


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_jwt()}"}


# ===========================================================================
# GET /api/v1/asoc/chat/threads
# ===========================================================================


class TestListChatThreads:
    def test_returns_threads_list(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = [_sample_thread()]
        app = _make_app(persistence)

        resp = TestClient(app).get(
            "/api/v1/asoc/chat/threads",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["threads"][0]["workspace_id"] == _WS
        assert data["threads"][0]["user_id"] == _USER_ID

    def test_empty_list_when_no_threads(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)

        resp = TestClient(app).get(
            "/api/v1/asoc/chat/threads",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_401_without_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/asoc/chat/threads"
        )

        assert resp.status_code == 401

    def test_workspace_derived_from_jwt(self) -> None:
        """Workspace passed to persistence must come from JWT project_id, not query param."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)

        TestClient(app).get(
            "/api/v1/asoc/chat/threads?workspace_id=ignored",
            headers=_auth_headers(),
        )

        persistence.list_threads.assert_called_once_with(_WS, _USER_ID)


# ===========================================================================
# GET /api/v1/asoc/chat/threads/{thread_id}/messages
# ===========================================================================


class TestListThreadMessages:
    def test_returns_messages(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _sample_thread()
        persistence.list_messages.return_value = [_sample_message()]
        app = _make_app(persistence)

        resp = TestClient(app).get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["messages"][0]["content"] == "Hello ASOC"

    def test_404_when_thread_not_found(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = None
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/asoc/chat/threads/not-a-uuid/messages",
            headers=_auth_headers(),
        )

        assert resp.status_code == 400

    def test_401_without_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages"
        )

        assert resp.status_code == 401

    def test_workspace_scoped_from_auth(self) -> None:
        """Workspace passed to persistence.get_thread comes from JWT."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _sample_thread()
        persistence.list_messages.return_value = []
        app = _make_app(persistence)

        TestClient(app).get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers=_auth_headers(),
        )

        persistence.get_thread.assert_called_once_with(_WS, _THREAD_ID)


# ===========================================================================
# DELETE /api/v1/asoc/chat/threads/{thread_id}
# ===========================================================================


class TestDeleteChatThread:
    def test_204_on_success(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        app = _make_app(persistence)

        resp = TestClient(app).delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 204

    def test_404_when_thread_not_found(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = False
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).delete(
            "/api/v1/asoc/chat/threads/not-a-uuid",
            headers=_auth_headers(),
        )

        assert resp.status_code == 400

    def test_401_without_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)

        resp = TestClient(app, raise_server_exceptions=False).delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}"
        )

        assert resp.status_code == 401

    def test_workspace_from_auth(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        app = _make_app(persistence)

        TestClient(app).delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers=_auth_headers(),
        )

        persistence.delete_thread.assert_called_once_with(_WS, _THREAD_ID)
