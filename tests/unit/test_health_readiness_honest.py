"""/health and /ready must go red when migrations did not apply (#539) or the
embedding model is missing (#541) — with an HTTP status, not just a body field."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.api.routes.health import _check_migrations
from metronix.core.config import Settings

HEALTH = "metronix.api.routes.health"


@pytest.fixture
def app():
    settings = Settings(
        METRONIX_ENV="development",
        DEFAULT_WORKSPACE_ID="TEST_WS",
        DEFAULT_WORKSPACE_NAME="Test Workspace",
    )
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestHealthReflectsStartupMigrations:
    def test_health_is_503_when_startup_migrations_failed(self, app, client) -> None:
        app.state.migrations_ok = False
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json() == {"status": "error", "migrations": "failed"}

    def test_health_is_200_when_startup_migrations_applied(self, app, client) -> None:
        app.state.migrations_ok = True
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@patch(f"{HEALTH}._check_ollama")
@patch(f"{HEALTH}._check_neo4j")
@patch(f"{HEALTH}._check_qdrant")
class TestReadyIncludesMigrations:
    def test_unapplied_migrations_make_ready_503(self, _q, _n, _o, client) -> None:
        with patch(f"{HEALTH}._check_migrations", side_effect=RuntimeError("at 033")):
            r = client.get("/ready")
        assert r.status_code == 503
        assert r.json()["status"] == "degraded"
        assert r.json()["services"]["migrations"] == "error"

    def test_all_ok_is_200(self, _q, _n, _o, client) -> None:
        with patch(f"{HEALTH}._check_migrations"):
            r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["services"]["migrations"] == "ok"

    def test_missing_embedding_model_makes_ready_503(self, _q, _n, mock_ollama, client) -> None:
        mock_ollama.side_effect = RuntimeError("embedding model missing")
        with patch(f"{HEALTH}._check_migrations"):
            r = client.get("/ready")
        assert r.status_code == 503
        assert r.json()["services"]["ollama"] == "error"


class TestCheckMigrations:
    def _engine_returning(self, revision: str | None) -> MagicMock:
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.scalar.return_value = revision
        return engine

    def test_db_at_head_passes(self) -> None:
        with (
            patch(f"{HEALTH}._alembic_head", return_value="034"),
            patch(f"{HEALTH}._sync_engine", return_value=self._engine_returning("034")),
        ):
            _check_migrations()

    @pytest.mark.parametrize("revision", ["033", None])
    def test_db_behind_head_or_empty_fails(self, revision: str | None) -> None:
        with (
            patch(f"{HEALTH}._alembic_head", return_value="034"),
            patch(f"{HEALTH}._sync_engine", return_value=self._engine_returning(revision)),
            pytest.raises(RuntimeError),
        ):
            _check_migrations()
