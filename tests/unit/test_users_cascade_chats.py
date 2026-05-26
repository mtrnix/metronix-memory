"""Unit tests for DELETE /api/v1/users/{user_id}/chats cascade endpoint (MTRNIX-353, T3).

Auth swapped from _require_admin (Metatron-internal JWT) to asoc_admin_auth
(static ASOC Bearer token) in MTRNIX-370 Phase 2a commit 5.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_chat_persistence
from metatron.api.routes.users import router as users_router
from metatron.auth.asoc_session import asoc_admin_auth
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import Settings

_USER_ID = "user-to-delete"


def _make_app(
    persistence: ChatPersistence,
    *,
    admin_authed: bool = True,
) -> FastAPI:
    """Build a minimal test app.

    ``admin_authed=True`` bypasses ``asoc_admin_auth`` so tests focus on
    endpoint behaviour.  ``admin_authed=False`` lets the real dependency run.
    """
    settings = Settings(METATRON_ENV="development")

    app = FastAPI()
    app.state.settings = settings
    app.include_router(users_router, prefix="/api/v1")
    app.dependency_overrides[get_chat_persistence] = lambda: persistence

    if admin_authed:
        app.dependency_overrides[asoc_admin_auth] = lambda: None

    return app


# ===========================================================================
# Happy path
# ===========================================================================


class TestDeleteUserChatsHappyPath:
    def test_204_when_threads_deleted(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 3
        app = _make_app(persistence)

        resp = TestClient(app).delete(f"/api/v1/users/{_USER_ID}/chats")

        assert resp.status_code == 204
        persistence.delete_threads_for_user.assert_called_once_with(_USER_ID)

    def test_204_when_no_threads_exist(self) -> None:
        """Idempotent — returns 204 even when the user has no chat history."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 0
        app = _make_app(persistence)

        resp = TestClient(app).delete(f"/api/v1/users/{_USER_ID}/chats")

        assert resp.status_code == 204

    def test_calls_delete_with_correct_user_id(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 1
        app = _make_app(persistence)

        TestClient(app).delete("/api/v1/users/specific-user-123/chats")

        persistence.delete_threads_for_user.assert_called_once_with("specific-user-123")


# ===========================================================================
# Auth gate
# ===========================================================================


class TestDeleteUserChatsAuthGate:
    def test_503_when_admin_token_not_configured(self) -> None:
        """When ASOC_MCP_ADMIN_TOKEN is not set, asoc_admin_auth returns 503."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 0

        settings = Settings(METATRON_ENV="development")  # no ASOC_MCP_ADMIN_TOKEN
        app = FastAPI()
        app.state.settings = settings
        app.include_router(users_router, prefix="/api/v1")
        app.dependency_overrides[get_chat_persistence] = lambda: persistence
        # Do NOT override asoc_admin_auth — let it fail-closed.

        resp = TestClient(app, raise_server_exceptions=False).delete(
            f"/api/v1/users/{_USER_ID}/chats"
        )
        assert resp.status_code == 503

    def test_401_when_wrong_bearer_token(self) -> None:
        """Providing a wrong Bearer token returns 401."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 0

        settings = Settings(METATRON_ENV="development", ASOC_MCP_ADMIN_TOKEN="correct-secret")
        app = FastAPI()
        app.state.settings = settings
        app.include_router(users_router, prefix="/api/v1")
        app.dependency_overrides[get_chat_persistence] = lambda: persistence

        resp = TestClient(app, raise_server_exceptions=False).delete(
            f"/api/v1/users/{_USER_ID}/chats",
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert resp.status_code == 401
