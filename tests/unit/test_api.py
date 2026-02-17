"""Tests for FastAPI REST API endpoints."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.workspaces.models import Workspace, WorkspaceStats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings() -> Settings:
    """Settings with test defaults (no real services required)."""
    return Settings(
        METATRON_ENV="development",
        DEFAULT_WORKSPACE_ID="TEST_WS",
        DEFAULT_WORKSPACE_NAME="Test Workspace",
        CORS_ORIGINS="http://localhost:3000,http://localhost:5173",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


_DEFAULT_WS = Workspace(
    workspace_id="TEST_WS",
    name="Test Workspace",
    user_id="user",
    is_active=True,
)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /ready
# ---------------------------------------------------------------------------

class TestReady:
    @patch("metatron.api.routes.health.httpx.get")
    @patch("metatron.storage.memgraph.get_memgraph_driver")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_ready_all_ok(
        self, mock_store, mock_driver, mock_httpx_get, client: TestClient,
    ) -> None:
        # Qdrant: mock collections
        store = MagicMock()
        store.client.get_collections.return_value = MagicMock(collections=[])
        mock_store.return_value = store
        # Memgraph: mock session
        session = MagicMock()
        session.__enter__ = lambda s: s
        session.__exit__ = MagicMock(return_value=False)
        driver = MagicMock()
        driver.session.return_value = session
        mock_driver.return_value = driver
        # Ollama: mock HTTP
        mock_httpx_get.return_value = MagicMock(status_code=200)

        r = client.get("/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["services"]["qdrant"] == "ok"
        assert body["services"]["memgraph"] == "ok"
        assert body["services"]["ollama"] == "ok"

    @patch("metatron.api.routes.health.httpx.get", side_effect=ConnectionError("no ollama"))
    @patch("metatron.storage.memgraph.get_memgraph_driver", side_effect=Exception("memgraph down"))
    @patch("metatron.storage.qdrant.get_hybrid_store", side_effect=Exception("qdrant down"))
    def test_ready_all_down_returns_503(
        self, mock_store, mock_driver, mock_httpx_get, client: TestClient,
    ) -> None:
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert "error" in body["services"]["qdrant"]
        assert "error" in body["services"]["memgraph"]
        assert "error" in body["services"]["ollama"]

    @patch("metatron.api.routes.health.httpx.get")
    @patch("metatron.storage.memgraph.get_memgraph_driver")
    @patch("metatron.storage.qdrant.get_hybrid_store", side_effect=Exception("qdrant down"))
    def test_ready_partial_degraded(
        self, mock_store, mock_driver, mock_httpx_get, client: TestClient,
    ) -> None:
        # Memgraph ok
        session = MagicMock()
        session.__enter__ = lambda s: s
        session.__exit__ = MagicMock(return_value=False)
        driver = MagicMock()
        driver.session.return_value = session
        mock_driver.return_value = driver
        # Ollama ok
        mock_httpx_get.return_value = MagicMock(status_code=200)

        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["services"]["memgraph"] == "ok"
        assert "error" in body["services"]["qdrant"]


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

class TestCORS:
    def test_cors_headers_present(self, client: TestClient) -> None:
        r = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" in r.headers

    def test_cors_allows_configured_origin(self, client: TestClient) -> None:
        r = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_wildcard_default(self) -> None:
        """With default CORS_ORIGINS='*', all origins are allowed."""
        app = create_app(Settings(METATRON_ENV="development"))
        c = TestClient(app)
        r = c.get("/health", headers={"Origin": "https://any-site.com"})
        assert r.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_metrics_returns_data(self, client: TestClient) -> None:
        r = client.get("/metrics")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_metrics_reset(self, client: TestClient) -> None:
        r = client.post("/metrics/reset")
        assert r.status_code == 200
        assert r.json()["status"] == "reset"


# ---------------------------------------------------------------------------
# /api/v1/chat
# ---------------------------------------------------------------------------

class TestChat:
    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer")
    def test_chat_returns_answer(
        self, mock_search, mock_mgr, client: TestClient,
    ) -> None:
        mock_mgr.return_value.get_active_workspace.return_value = _DEFAULT_WS
        mock_search.return_value = "The answer is 42."

        r = client.post("/api/v1/chat", json={
            "question": "What is the meaning of life?",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] == "The answer is 42."
        assert body["workspace_id"] == "TEST_WS"

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer")
    def test_chat_with_workspace_id(
        self, mock_search, mock_mgr, client: TestClient,
    ) -> None:
        mock_search.return_value = "Answer for PROJ."

        r = client.post("/api/v1/chat", json={
            "question": "Tell me about the project",
            "workspace_id": "PROJ",
        })
        assert r.status_code == 200
        assert r.json()["workspace_id"] == "PROJ"

    def test_chat_empty_question_rejected(self, client: TestClient) -> None:
        r = client.post("/api/v1/chat", json={"question": ""})
        assert r.status_code == 422

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer",
           side_effect=RuntimeError("LLM error"))
    def test_chat_search_error_returns_500(
        self, mock_search, mock_mgr, client: TestClient,
    ) -> None:
        mock_mgr.return_value.get_active_workspace.return_value = _DEFAULT_WS
        r = client.post("/api/v1/chat", json={"question": "hello"})
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# /api/v1/chat/stream
# ---------------------------------------------------------------------------

class TestChatStream:
    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer")
    def test_stream_returns_sse_events(
        self, mock_search, mock_mgr, client: TestClient,
    ) -> None:
        mock_mgr.return_value.get_active_workspace.return_value = _DEFAULT_WS
        mock_search.return_value = (
            "First sentence. Second sentence."
            "\n\n\U0001f4da Sources:\n\U0001f4c4 Design Doc"
        )

        with client.stream("POST", "/api/v1/chat/stream", json={
            "question": "Tell me about the project",
        }) as r:
            assert r.status_code == 200
            content_type = r.headers.get("content-type", "")
            assert "text/event-stream" in content_type

            raw = b""
            for chunk in r.iter_bytes():
                raw += chunk

        text = raw.decode()
        # Should contain status, chunk, sources, and done events
        assert "event: status" in text
        assert "event: chunk" in text
        assert "event: sources" in text
        assert "event: done" in text
        # Verify sources content
        assert "Design Doc" in text

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer",
           side_effect=RuntimeError("LLM boom"))
    def test_stream_error_sends_error_event(
        self, mock_search, mock_mgr, client: TestClient,
    ) -> None:
        mock_mgr.return_value.get_active_workspace.return_value = _DEFAULT_WS

        with client.stream("POST", "/api/v1/chat/stream", json={
            "question": "hello",
        }) as r:
            raw = b""
            for chunk in r.iter_bytes():
                raw += chunk

        text = raw.decode()
        assert "event: error" in text
        assert "LLM boom" in text
        assert "event: done" in text


# ---------------------------------------------------------------------------
# /api/v1/upload
# ---------------------------------------------------------------------------

class TestUpload:
    @patch("metatron.api.routes.chat._ingest_text")
    def test_upload_text_file(self, mock_ingest, client: TestClient) -> None:
        mock_ingest.return_value = {
            "chunks": 3,
            "workspace_id": "TEST_WS",
            "graph_extracted": True,
        }
        r = client.post(
            "/api/v1/upload",
            files={"file": ("doc.txt", BytesIO(b"Hello world"), "text/plain")},
            data={"user_id": "u1", "workspace_id": "TEST_WS"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["file_name"] == "doc.txt"
        assert body["chunks"] == 3

    def test_upload_empty_file_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/upload",
            files={"file": ("empty.txt", BytesIO(b""), "text/plain")},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# /api/v1/workspaces
# ---------------------------------------------------------------------------

class TestWorkspaces:
    @patch("metatron.api.routes.workspaces.get_workspace_manager")
    def test_list_workspaces(self, mock_mgr, client: TestClient) -> None:
        mock_mgr.return_value.list_workspaces.return_value = [_DEFAULT_WS]
        r = client.get("/api/v1/workspaces/")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["workspaces"][0]["workspace_id"] == "TEST_WS"

    @patch("metatron.api.routes.workspaces.get_workspace_manager")
    def test_create_workspace(self, mock_mgr, client: TestClient) -> None:
        new_ws = Workspace(workspace_id="NEW", name="New WS", user_id="user")
        mock_mgr.return_value.create_workspace.return_value = new_ws
        r = client.post("/api/v1/workspaces/", json={
            "name": "New WS",
            "user_id": "user",
        })
        assert r.status_code == 201
        assert r.json()["workspace_id"] == "NEW"

    @patch("metatron.api.routes.workspaces.get_workspace_manager")
    def test_get_workspace(self, mock_mgr, client: TestClient) -> None:
        mock_mgr.return_value.get_workspace.return_value = _DEFAULT_WS
        r = client.get("/api/v1/workspaces/TEST_WS")
        assert r.status_code == 200
        assert r.json()["name"] == "Test Workspace"

    @patch("metatron.api.routes.workspaces.get_workspace_manager")
    def test_get_workspace_not_found(self, mock_mgr, client: TestClient) -> None:
        mock_mgr.return_value.get_workspace.return_value = None
        r = client.get("/api/v1/workspaces/NOPE")
        assert r.status_code == 404

    @patch("metatron.storage.memgraph.delete_workspace_graph")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    @patch("metatron.api.routes.workspaces.get_workspace_manager")
    def test_delete_workspace(
        self, mock_mgr, mock_store, mock_graph, client: TestClient,
    ) -> None:
        mock_mgr.return_value.get_workspace.return_value = _DEFAULT_WS
        mock_mgr.return_value.delete_workspace.return_value = True
        store = MagicMock()
        mock_store.return_value = store

        r = client.delete("/api/v1/workspaces/TEST_WS?user_id=user")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    @patch("metatron.api.routes.workspaces.get_workspace_manager")
    def test_activate_workspace(self, mock_mgr, client: TestClient) -> None:
        mock_mgr.return_value.get_workspace.return_value = _DEFAULT_WS
        mock_mgr.return_value.set_active_workspace.return_value = True
        r = client.post("/api/v1/workspaces/TEST_WS/activate?user_id=user")
        assert r.status_code == 200
        assert r.json()["status"] == "activated"


# ---------------------------------------------------------------------------
# /api/v1/connections/sync/{type}
# ---------------------------------------------------------------------------

class TestConnectionSync:
    @patch("metatron.api.routes.connections._run_sync")
    @patch("metatron.api.routes.connections._config_from_env")
    @patch("metatron.api.routes.connections._get_registry")
    def test_sync_by_type_starts_background_task(
        self, mock_registry, mock_config, mock_run, client: TestClient,
    ) -> None:
        mock_registry.return_value.is_registered.return_value = True
        mock_config.return_value = {"url": "https://jira.test", "username": "u", "api_token": "t", "project_key": "P"}

        r = client.post("/api/v1/connections/sync/jira")
        assert r.status_code == 200
        assert r.json()["status"] == "sync_started"

    @patch("metatron.api.routes.connections._get_registry")
    def test_sync_unknown_type_400(self, mock_registry, client: TestClient) -> None:
        mock_registry.return_value.is_registered.return_value = False
        mock_registry.return_value.list_available.return_value = ["confluence", "jira"]
        r = client.post("/api/v1/connections/sync/notion")
        assert r.status_code == 400
        assert "Unknown connector" in r.json()["detail"]

    @patch("metatron.api.routes.connections._config_from_env", return_value={})
    @patch("metatron.api.routes.connections._get_registry")
    def test_sync_no_env_config_400(
        self, mock_registry, mock_config, client: TestClient,
    ) -> None:
        mock_registry.return_value.is_registered.return_value = True
        r = client.post("/api/v1/connections/sync/confluence")
        assert r.status_code == 400
        assert "No environment config" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /api/v1/admin
# ---------------------------------------------------------------------------

class TestAdmin:
    @patch("metatron.api.routes.admin.get_cleanup_preview")
    def test_cleanup_preview(self, mock_preview, client: TestClient) -> None:
        mock_preview.return_value = {
            "cleanup_allowed": False,
            "qdrant": {"collections": [], "total_points": 0},
            "memgraph": {"nodes": 0, "relationships": 0},
        }
        r = client.get("/api/v1/admin/cleanup/preview")
        assert r.status_code == 200
        assert "cleanup_allowed" in r.json()

    def test_cleanup_workspace_requires_header(self, client: TestClient) -> None:
        r = client.delete("/api/v1/admin/cleanup/workspace/TEST_WS")
        assert r.status_code == 400
        assert "X-Confirm-Cleanup" in r.json()["detail"]

    def test_cleanup_all_requires_header(self, client: TestClient) -> None:
        r = client.delete("/api/v1/admin/cleanup/all")
        assert r.status_code == 400
        assert "DELETE-ALL-DATA" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Helpers (sentence splitting)
# ---------------------------------------------------------------------------

class TestSentenceSplitter:
    def test_splits_on_sentence_boundaries(self) -> None:
        from metatron.api.routes.chat import _split_into_sentences
        text = "First sentence. Second sentence. Third sentence here."
        chunks = _split_into_sentences(text)
        assert len(chunks) >= 1
        # All text is preserved
        assert "".join(chunks).replace(" ", "") == text.replace(" ", "")

    def test_empty_string_returns_original(self) -> None:
        from metatron.api.routes.chat import _split_into_sentences
        assert _split_into_sentences("") == [""]

    def test_short_text_single_chunk(self) -> None:
        from metatron.api.routes.chat import _split_into_sentences
        assert _split_into_sentences("Hi.") == ["Hi."]


class TestSourceExtraction:
    def test_extracts_sources(self) -> None:
        from metatron.api.routes.chat import _extract_sources_section
        answer = "The answer.\n\n\U0001f4da Sources:\n\U0001f4c4 Doc A\n\U0001f4cb Task B"
        body, sources = _extract_sources_section(answer)
        assert body == "The answer."
        assert len(sources) == 2
        assert "\U0001f4c4 Doc A" in sources

    def test_no_sources_section(self) -> None:
        from metatron.api.routes.chat import _extract_sources_section
        body, sources = _extract_sources_section("Just an answer.")
        assert body == "Just an answer."
        assert sources == []
