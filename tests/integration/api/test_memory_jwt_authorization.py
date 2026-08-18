"""HTTP authorization conformance for protected memory mutations."""

from __future__ import annotations

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metronix.api.middleware import OptionalAuthMiddleware
from metronix.api.routes import memory
from metronix.auth.jwt import create_token
from metronix.auth.policy import AuthorizationEvaluator
from metronix.core.config import Settings


class _EmptyGrantStore:
    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[object]:
        return []


class _PersonalKeyStore:
    async def resolve_key(self, token: str) -> dict[str, str] | None:
        return {"user_id": "key-delegate", "source": "personal"}


class _UserStore:
    async def get_user_by_id(self, user_id: str) -> dict[str, object] | None:
        return {
            "id": user_id,
            "role": "editor",
            "workspace_ids": ["key-workspace"],
            "is_active": True,
        }


def _app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        AUTH_ENABLED=True,
        METRONIX_SECRET_KEY="jwt-conformance-secret-with-at-least-32-characters",
    )
    app.include_router(memory.router, prefix="/api/v1")
    app.add_middleware(OptionalAuthMiddleware)
    return app


def test_verified_jwt_denial_happens_before_memory_service_construction(monkeypatch) -> None:
    """A valid principal without an agent grant cannot reach memory storage."""
    app = _app()

    service_factory = Mock()
    monkeypatch.setattr(memory, "get_memory_service", service_factory)
    monkeypatch.setattr(
        memory,
        "get_authorization_evaluator",
        lambda: AuthorizationEvaluator(_EmptyGrantStore()),
    )
    token = create_token(
        user_id="jwt-delegate",
        role="editor",
        workspace_ids=["jwt-workspace"],
        secret_key=app.state.settings.secret_key,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/memory/records",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "must not reach storage", "agent_id": "ungranted-agent"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "memory_access_denied"
    assert response.json()["detail"]["reason"] == "no_active_grant"
    service_factory.assert_not_called()


def test_verified_personal_key_denial_happens_before_memory_service_construction(
    monkeypatch,
) -> None:
    """A resolved personal-key principal has the same pre-storage denial boundary."""
    app = _app()
    app.state.api_key_store = _PersonalKeyStore()
    app.state.user_store = _UserStore()
    service_factory = Mock()
    monkeypatch.setattr(memory, "get_memory_service", service_factory)
    monkeypatch.setattr(
        memory,
        "get_authorization_evaluator",
        lambda: AuthorizationEvaluator(_EmptyGrantStore()),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/memory/records",
            headers={"Authorization": "Bearer mtk_personal_key_fixture"},
            json={"content": "must not reach storage", "agent_id": "ungranted-agent"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "memory_access_denied"
    assert response.json()["detail"]["reason"] == "no_active_grant"
    service_factory.assert_not_called()
