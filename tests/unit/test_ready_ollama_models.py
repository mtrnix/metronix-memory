"""/ready must not report Ollama as ok while the embedding model is missing (#541)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.api.routes.health import _check_ollama
from metronix.core.config import Settings

EMBED_MODEL = "nomic-embed-text"


def _tags_response(*names: str, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"models": [{"name": n} for n in names]}
    return response


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        METRONIX_ENV="development",
        DEFAULT_WORKSPACE_ID="TEST_WS",
        DEFAULT_WORKSPACE_NAME="Test Workspace",
        OLLAMA_EMBED_MODEL=EMBED_MODEL,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


class TestCheckOllama:
    def test_no_models_is_an_error(self) -> None:
        with patch("httpx.get", return_value=_tags_response()), pytest.raises(RuntimeError):
            _check_ollama("http://ollama:11434", EMBED_MODEL)

    def test_other_models_only_is_an_error(self) -> None:
        with (
            patch("httpx.get", return_value=_tags_response("qwen2.5:3b")),
            pytest.raises(RuntimeError),
        ):
            _check_ollama("http://ollama:11434", EMBED_MODEL)

    @pytest.mark.parametrize("installed", [EMBED_MODEL, f"{EMBED_MODEL}:latest"])
    def test_embed_model_present_is_ok(self, installed: str) -> None:
        with patch("httpx.get", return_value=_tags_response("qwen2.5:3b", installed)):
            _check_ollama("http://ollama:11434", EMBED_MODEL)

    def test_http_error_is_an_error(self) -> None:
        with (
            patch("httpx.get", return_value=_tags_response(EMBED_MODEL, status_code=500)),
            pytest.raises(RuntimeError),
        ):
            _check_ollama("http://ollama:11434", EMBED_MODEL)


class TestReadyEndpoint:
    @patch("metronix.api.routes.health._check_neo4j")
    @patch("metronix.api.routes.health._check_qdrant")
    def test_ollama_up_without_models_is_degraded(
        self, _qdrant: MagicMock, _neo4j: MagicMock, client: TestClient
    ) -> None:
        with patch("httpx.get", return_value=_tags_response()):
            body = client.get("/ready").json()
        assert body["services"]["ollama"] == "error"
        assert body["status"] == "degraded"

    @patch("metronix.api.routes.health._check_neo4j")
    @patch("metronix.api.routes.health._check_qdrant")
    def test_ollama_with_embed_model_is_ready(
        self, _qdrant: MagicMock, _neo4j: MagicMock, client: TestClient
    ) -> None:
        with patch("httpx.get", return_value=_tags_response(f"{EMBED_MODEL}:latest")):
            body = client.get("/ready").json()
        assert body["services"]["ollama"] == "ok"
        assert body["status"] == "ready"
