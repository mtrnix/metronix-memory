"""Unit tests for ASOC chat REST endpoints after T4 auth swap (MTRNIX-354).

Tests the updated routes:
- POST /api/v1/asoc/chat           — requires asoc_auth (JWT), returns SSE
- GET  /api/v1/asoc/chat/threads   — requires asoc_auth
- GET  /api/v1/asoc/chat/threads/{id}/messages — requires asoc_auth
- DELETE /api/v1/asoc/chat/threads/{id} — requires asoc_auth

The old T3 skeleton required require_viewer/require_editor.  These tests verify
that all 4 endpoints now use asoc_auth and derive workspace from the JWT.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as pyjwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_chat_persistence
from metatron.api.routes.asoc_chat import router as asoc_chat_router
from metatron.chat.models import ChatMessage, ChatMessageRole, ChatThread
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import Settings

_SECRET = "test-secret-key"
_ALGO = "HS256"
_INSTANCE = "pilot"
_PROJECT_ID = "proj-42"
_USER_ID = "user-1"
_THREAD_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_MSG_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)

_EXPECTED_WS = f"asoc-{_INSTANCE}-{_PROJECT_ID}"


def _make_jwt(
    user_id: str = _USER_ID,
    project_id: str = _PROJECT_ID,
    exp_offset: int = 3600,
) -> str:
    return pyjwt.encode(
        {
            "sub": user_id,
            "project_id": project_id,
            "exp": int(time.time()) + exp_offset,
        },
        _SECRET,
        algorithm=_ALGO,
    )


def _make_thread(**overrides: Any) -> ChatThread:
    base: dict[str, Any] = {
        "thread_id": _THREAD_ID,
        "workspace_id": _EXPECTED_WS,
        "user_id": _USER_ID,
        "created_at": _NOW,
        "last_message_at": None,
    }
    base.update(overrides)
    return ChatThread(**base)


def _make_message(**overrides: Any) -> ChatMessage:
    base: dict[str, Any] = {
        "id": _MSG_ID,
        "thread_id": _THREAD_ID,
        "role": ChatMessageRole.USER,
        "content": "test message",
        "citations_json": None,
        "tool_calls_json": None,
        "created_at": _NOW,
    }
    base.update(overrides)
    return ChatMessage(**base)


def _make_app(persistence: Any = None, orch: Any = None) -> FastAPI:
    """Create a minimal FastAPI app with the ASOC chat router and real asoc_auth."""
    settings = Settings(
        ASOC_SHARED_SECRET=_SECRET,
        ASOC_JWT_ALGORITHM=_ALGO,
        METATRON_ASOC_INSTANCE_ID=_INSTANCE,
    )

    app = FastAPI()
    app.state.settings = settings

    # Wire optional orchestrator for POST /chat tests
    if orch is not None:
        app.state.asoc_chat_orchestrator = orch
    # else: asoc_chat_orchestrator not set → 503

    app.include_router(asoc_chat_router, prefix="/api/v1/asoc")

    if persistence is not None:
        app.dependency_overrides[get_chat_persistence] = lambda: persistence

    return app


# ===========================================================================
# GET /api/v1/asoc/chat/threads
# ===========================================================================


class TestListChatThreadsT4:
    def test_requires_valid_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        # No Authorization header
        resp = client.get("/api/v1/asoc/chat/threads")
        assert resp.status_code == 401

    def test_returns_threads_for_jwt_workspace(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = [_make_thread()]
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.get(
            "/api/v1/asoc/chat/threads",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["threads"][0]["workspace_id"] == _EXPECTED_WS

    def test_workspace_derived_from_jwt_not_query_param(self) -> None:
        """Workspace comes from JWT project_id, not from workspace_id query param."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.get(
            "/api/v1/asoc/chat/threads?workspace_id=ignored-workspace",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        # persistence.list_threads called with correct JWT-derived workspace
        persistence.list_threads.assert_called_once_with(_EXPECTED_WS, _USER_ID)

    def test_expired_jwt_returns_401(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        expired = _make_jwt(exp_offset=-60)
        resp = client.get(
            "/api/v1/asoc/chat/threads",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/asoc/chat/threads/{thread_id}/messages
# ===========================================================================


class TestListThreadMessagesT4:
    def test_requires_valid_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages")
        assert resp.status_code == 401

    def test_returns_messages_for_valid_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _make_thread()
        persistence.list_messages.return_value = [_make_message()]
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["messages"][0]["content"] == "test message"

    def test_404_when_thread_not_in_workspace(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = None  # not found in JWT workspace
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.get(
            "/api/v1/asoc/chat/threads/not-a-uuid/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_workspace_scoped_from_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _make_thread()
        persistence.list_messages.return_value = []
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )

        # get_thread must be called with JWT-derived workspace
        persistence.get_thread.assert_called_once_with(_EXPECTED_WS, _THREAD_ID)


# ===========================================================================
# DELETE /api/v1/asoc/chat/threads/{thread_id}
# ===========================================================================


class TestDeleteChatThreadT4:
    def test_requires_valid_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(f"/api/v1/asoc/chat/threads/{_THREAD_ID}")
        assert resp.status_code == 401

    def test_204_on_success(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

    def test_404_when_thread_not_found(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = False
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.delete(
            "/api/v1/asoc/chat/threads/not-a-uuid",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_workspace_scoped_from_jwt(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        persistence.delete_thread.assert_called_once_with(_EXPECTED_WS, _THREAD_ID)


# ===========================================================================
# POST /api/v1/asoc/chat
# ===========================================================================


class TestAsocChatPost:
    def test_requires_valid_jwt(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/api/v1/asoc/chat", json={"message": "hello"})
        assert resp.status_code == 401

    def test_503_when_orchestrator_not_configured(self) -> None:
        app = _make_app()  # no orchestrator on app.state
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503

    def test_empty_message_returns_422(self) -> None:
        """Empty message violates min_length=1.

        Note: FastAPI resolves route-level dependencies (auth) before body
        validation. When the orchestrator is missing we get 503; we need a
        configured orchestrator to reach body validation.
        """
        mock_orch = MagicMock()
        app = _make_app(orch=mock_orch)
        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Empty message violates min_length=1
        assert resp.status_code == 422

    def test_rate_limit_exhausted_returns_429_not_sse(self) -> None:
        """Rate-limit check happens BEFORE SSE stream opens — client gets HTTP 429."""
        from unittest.mock import AsyncMock as _AsyncMock

        mock_orch = MagicMock()
        app = _make_app(orch=mock_orch)

        # Wire a rate limiter that denies all requests.
        rate_limiter = _AsyncMock()
        rate_limiter.acquire.return_value = False
        app.state.asoc_rate_limiter = rate_limiter

        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Must be HTTP 429, NOT a 200 SSE stream with an error event inside.
        assert resp.status_code == 429
        assert resp.json()["detail"] == "rate_limited"
        # Orchestrator.run must never have been called.
        mock_orch.run.assert_not_called()

    def test_rate_limit_allowed_opens_sse_stream(self) -> None:
        """Rate-limit passes → orchestrator.run() is called and returns SSE."""
        from unittest.mock import AsyncMock as _AsyncMock

        async def _gen(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            yield {"event": "done", "data": "{}"}

        mock_orch = MagicMock()
        mock_orch.run.return_value = _gen()
        app = _make_app(orch=mock_orch)

        rate_limiter = _AsyncMock()
        rate_limiter.acquire.return_value = True  # allow
        app.state.asoc_rate_limiter = rate_limiter

        client = TestClient(app, raise_server_exceptions=False)

        token = _make_jwt()
        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        mock_orch.run.assert_called_once()
