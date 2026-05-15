"""Unit tests for DELETE /api/v1/users/{user_id}/chats cascade endpoint (MTRNIX-353, T3)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_chat_persistence
from metatron.api.routes.users import router as users_router
from metatron.auth.dependencies import get_current_user
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import Settings
from metatron.core.models import Role, User

_USER_ID = "user-to-delete"


def _make_user(role: Role = Role.ADMIN) -> User:
    return User(
        id="admin-caller",
        username="admin",
        email="admin@example.com",
        role=role,
        workspace_ids=["*"],
    )


def _make_app(
    persistence: ChatPersistence,
    role: Role = Role.ADMIN,
    *,
    auth_enabled: bool = False,
) -> FastAPI:
    user = _make_user(role=role)
    settings = Settings(METATRON_ENV="development", AUTH_ENABLED=auth_enabled)

    app = FastAPI()
    app.state.settings = settings
    app.include_router(users_router, prefix="/api/v1")

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_chat_persistence] = lambda: persistence

    # _require_admin reads request.state.user["role"] (set by OptionalAuthMiddleware
    # in production). We inject it here so tests work without starting the full app.
    from fastapi import Request as _Request

    _role_str = role.value

    @app.middleware("http")
    async def inject_user_state(request: _Request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = {"role": _role_str, "user_id": "test-caller"}
        return await call_next(request)

    return app


# ===========================================================================
# Happy path
# ===========================================================================


class TestDeleteUserChatsHappyPath:
    def test_204_when_threads_deleted(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 3
        app = _make_app(persistence, role=Role.ADMIN)

        resp = TestClient(app).delete(f"/api/v1/users/{_USER_ID}/chats")

        assert resp.status_code == 204
        persistence.delete_threads_for_user.assert_called_once_with(_USER_ID)

    def test_204_when_no_threads_exist(self) -> None:
        """Idempotent — returns 204 even when the user has no chat history."""
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 0
        app = _make_app(persistence, role=Role.ADMIN)

        resp = TestClient(app).delete(f"/api/v1/users/{_USER_ID}/chats")

        assert resp.status_code == 204

    def test_calls_delete_with_correct_user_id(self) -> None:
        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 1
        app = _make_app(persistence, role=Role.ADMIN)

        TestClient(app).delete("/api/v1/users/specific-user-123/chats")

        persistence.delete_threads_for_user.assert_called_once_with("specific-user-123")


# ===========================================================================
# RBAC gate
# ===========================================================================


class TestDeleteUserChatsRBAC:
    def test_403_when_not_admin(self) -> None:
        """Only admins may call the cascade delete endpoint.

        _require_admin reads ``request.state.user["role"]`` set by
        ``OptionalAuthMiddleware`` (not the ``get_current_user`` dependency).
        We inject the non-admin role via a middleware so the check fires.
        """
        from fastapi import Request

        persistence = AsyncMock(spec=ChatPersistence)
        persistence.delete_threads_for_user.return_value = 0

        settings = Settings(METATRON_ENV="development", AUTH_ENABLED=True)
        user = _make_user(role=Role.EDITOR)

        app2 = FastAPI()
        app2.state.settings = settings
        app2.include_router(users_router, prefix="/api/v1")
        app2.dependency_overrides[get_current_user] = lambda: user
        app2.dependency_overrides[get_chat_persistence] = lambda: persistence

        @app2.middleware("http")
        async def set_user_state(request: Request, call_next):  # type: ignore[no-untyped-def]
            request.state.user = {"role": "editor", "user_id": "editor-u1"}
            return await call_next(request)

        resp = TestClient(app2, raise_server_exceptions=False).delete(
            f"/api/v1/users/{_USER_ID}/chats"
        )
        assert resp.status_code == 403
