"""Unit tests for ASOC chat REST endpoints after Phase 2a auth swap (MTRNIX-370).

Tests the updated routes:
- POST /api/v1/asoc/chat           — requires X-ASOC-Session, returns SSE
- GET  /api/v1/asoc/chat/threads   — requires X-ASOC-Session + workspace_id query param
- GET  /api/v1/asoc/chat/threads/{id}/messages — requires X-ASOC-Session + workspace_id
- DELETE /api/v1/asoc/chat/threads/{id} — requires X-ASOC-Session + workspace_id

Phase 2a: JWT-based asoc_auth replaced with session-based asoc_chat_auth.
Workspace comes from query params / body, NOT from JWT claims.
Tests use dependency override to avoid real ASOC MCP calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_chat_persistence
from metatron.api.routes.asoc_chat import router as asoc_chat_router
from metatron.auth.asoc_session import AsocAuthContext, asoc_chat_auth
from metatron.chat.models import ChatMessage, ChatMessageRole, ChatThread
from metatron.chat.persistence import ChatPersistence

_SESSION_ID = "test-session-id-abc"
_INSTANCE = "pilot"
_USER_ID = "user-1"
_WORKSPACE_ID = f"asoc-{_INSTANCE}-proj-42"
_THREAD_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_MSG_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)


def _make_auth_context(
    user_id: str = _USER_ID,
    session_id: str = _SESSION_ID,
) -> AsocAuthContext:
    return AsocAuthContext(
        session_id=session_id,
        user_id=user_id,
        username="testuser",
        display_name="Test User",
        email="test@example.com",
        roles=["viewer"],
    )


def _make_thread(**overrides: Any) -> ChatThread:
    base: dict[str, Any] = {
        "thread_id": _THREAD_ID,
        "workspace_id": _WORKSPACE_ID,
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


def _make_app(
    persistence: Any = None,
    orch: Any = None,
    auth_ctx: AsocAuthContext | None = None,
    auth_raises: Exception | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with the ASOC chat router.

    The ``asoc_chat_auth`` dependency is overridden to avoid real MCP calls:
    - If ``auth_ctx`` is provided → returns that context.
    - If ``auth_raises`` is provided → raises that exception.
    - Otherwise → returns the default ``_make_auth_context()``.
    """
    app = FastAPI()

    # Override asoc_chat_auth to avoid real ASOC MCP calls.
    if auth_raises is not None:

        async def _auth_override() -> AsocAuthContext:
            raise auth_raises  # type: ignore[misc]
    else:
        _ctx = auth_ctx or _make_auth_context()

        async def _auth_override() -> AsocAuthContext:
            return _ctx

    app.dependency_overrides[asoc_chat_auth] = _auth_override

    # Wire optional orchestrator for POST /chat tests
    if orch is not None:
        app.state.asoc_chat_orchestrator = orch

    app.include_router(asoc_chat_router, prefix="/api/v1/asoc")

    if persistence is not None:
        app.dependency_overrides[get_chat_persistence] = lambda: persistence

    return app


# ===========================================================================
# GET /api/v1/asoc/chat/threads
# ===========================================================================


class TestListChatThreads:
    def test_missing_session_returns_401(self) -> None:
        """Without X-ASOC-Session header → 401."""
        from fastapi import HTTPException

        app = _make_app(
            auth_raises=HTTPException(status_code=401, detail="missing_x_asoc_session_header")
        )
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app.dependency_overrides[get_chat_persistence] = lambda: persistence
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/asoc/chat/threads?workspace_id={_WORKSPACE_ID}")
        assert resp.status_code == 401

    def test_missing_workspace_id_query_returns_422(self) -> None:
        """workspace_id query param is required."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/v1/asoc/chat/threads")
        assert resp.status_code == 422

    def test_returns_threads_for_workspace(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = [_make_thread()]
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            f"/api/v1/asoc/chat/threads?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["threads"][0]["workspace_id"] == _WORKSPACE_ID

    def test_workspace_from_query_param_not_jwt(self) -> None:
        """Workspace comes from query param, NOT from auth context."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.list_threads.return_value = []
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        custom_ws = "asoc-prod-custom-workspace"
        resp = client.get(
            f"/api/v1/asoc/chat/threads?workspace_id={custom_ws}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )

        assert resp.status_code == 200
        persistence.list_threads.assert_called_once_with(custom_ws, _USER_ID)


# ===========================================================================
# GET /api/v1/asoc/chat/threads/{thread_id}/messages
# ===========================================================================


class TestListThreadMessages:
    def test_missing_session_returns_401(self) -> None:
        from fastapi import HTTPException

        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(
            persistence,
            auth_raises=HTTPException(status_code=401, detail="missing"),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages?workspace_id={_WORKSPACE_ID}"
        )
        assert resp.status_code == 401

    def test_missing_workspace_id_returns_422(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 422

    def test_returns_messages_for_valid_session(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _make_thread()
        persistence.list_messages.return_value = [_make_message()]
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["messages"][0]["content"] == "test message"

    def test_404_when_thread_not_in_workspace(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = None
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            f"/api/v1/asoc/chat/threads/not-a-uuid/messages?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 400

    def test_workspace_scoped_from_query_param(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.get_thread.return_value = _make_thread()
        persistence.list_messages.return_value = []
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        client.get(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}/messages?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )

        persistence.get_thread.assert_called_once_with(_WORKSPACE_ID, _THREAD_ID)


# ===========================================================================
# DELETE /api/v1/asoc/chat/threads/{thread_id}
# ===========================================================================


class TestDeleteChatThread:
    def test_missing_session_returns_401(self) -> None:
        from fastapi import HTTPException

        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(
            persistence,
            auth_raises=HTTPException(status_code=401, detail="missing"),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}?workspace_id={_WORKSPACE_ID}"
        )
        assert resp.status_code == 401

    def test_missing_workspace_id_returns_422(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 422

    def test_204_on_success(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 204

    def test_404_when_thread_not_found(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = False
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 404

    def test_400_on_invalid_uuid(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete(
            f"/api/v1/asoc/chat/threads/not-a-uuid?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 400

    def test_workspace_scoped_from_query_param(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_thread.return_value = True
        app = _make_app(persistence)
        client = TestClient(app, raise_server_exceptions=False)

        client.delete(
            f"/api/v1/asoc/chat/threads/{_THREAD_ID}?workspace_id={_WORKSPACE_ID}",
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        persistence.delete_thread.assert_called_once_with(_WORKSPACE_ID, _THREAD_ID)


# ===========================================================================
# POST /api/v1/asoc/chat
# ===========================================================================


class TestAsocChatPost:
    def test_missing_session_returns_401(self) -> None:
        from fastapi import HTTPException

        app = _make_app(auth_raises=HTTPException(status_code=401, detail="missing"))
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello", "workspace_id": _WORKSPACE_ID},
        )
        assert resp.status_code == 401

    def test_503_when_orchestrator_not_configured(self) -> None:
        app = _make_app()  # no orchestrator on app.state
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello", "workspace_id": _WORKSPACE_ID},
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 503

    def test_missing_workspace_id_in_body_returns_422(self) -> None:
        """workspace_id is required in body."""
        mock_orch = MagicMock()
        app = _make_app(orch=mock_orch)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello"},
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 422

    def test_empty_message_returns_422(self) -> None:
        """Empty message violates min_length=1."""
        mock_orch = MagicMock()
        app = _make_app(orch=mock_orch)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "", "workspace_id": _WORKSPACE_ID},
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 422

    def test_rate_limit_exhausted_returns_429_not_sse(self) -> None:
        """Rate-limit check happens BEFORE SSE stream opens — client gets HTTP 429."""
        mock_orch = MagicMock()
        app = _make_app(orch=mock_orch)

        # Wire a rate limiter that denies all requests.
        rate_limiter = AsyncMock()
        rate_limiter.acquire.return_value = False
        app.state.asoc_rate_limiter = rate_limiter

        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello", "workspace_id": _WORKSPACE_ID},
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        # Must be HTTP 429, NOT a 200 SSE stream with an error event inside.
        assert resp.status_code == 429
        assert resp.json()["detail"] == "rate_limited"
        # Orchestrator.run must never have been called.
        mock_orch.run.assert_not_called()

    def test_rate_limit_allowed_opens_sse_stream(self) -> None:
        """Rate-limit passes → orchestrator.run() is called and returns SSE."""

        async def _gen(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            yield {"event": "done", "data": "{}"}

        mock_orch = MagicMock()
        mock_orch.run.return_value = _gen()
        app = _make_app(orch=mock_orch)

        rate_limiter = AsyncMock()
        rate_limiter.acquire.return_value = True  # allow
        app.state.asoc_rate_limiter = rate_limiter

        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/asoc/chat",
            json={"message": "hello", "workspace_id": _WORKSPACE_ID},
            headers={"X-ASOC-Session": _SESSION_ID},
        )
        assert resp.status_code == 200
        mock_orch.run.assert_called_once()
