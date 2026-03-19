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
    @patch("metatron.api.routes.health._check_ollama")
    @patch("metatron.api.routes.health._check_memgraph")
    @patch("metatron.api.routes.health._check_qdrant")
    def test_ready_all_ok(
        self, mock_qdrant, mock_memgraph, mock_ollama, client: TestClient,
    ) -> None:
        r = client.get("/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["services"]["qdrant"] == "ok"
        assert body["services"]["memgraph"] == "ok"
        assert body["services"]["ollama"] == "ok"

    @patch("metatron.api.routes.health._check_ollama", side_effect=ConnectionError("no ollama"))
    @patch("metatron.api.routes.health._check_memgraph", side_effect=Exception("memgraph down"))
    @patch("metatron.api.routes.health._check_qdrant", side_effect=Exception("qdrant down"))
    def test_ready_all_down_returns_503(
        self, mock_qdrant, mock_memgraph, mock_ollama, client: TestClient,
    ) -> None:
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["services"]["qdrant"] == "error"
        assert body["services"]["memgraph"] == "error"
        assert body["services"]["ollama"] == "error"

    @patch("metatron.api.routes.health._check_ollama", side_effect=ConnectionError("no ollama"))
    @patch("metatron.api.routes.health._check_memgraph", side_effect=Exception("memgraph down"))
    @patch("metatron.api.routes.health._check_qdrant", side_effect=Exception("qdrant down"))
    def test_ready_error_no_details(
        self, mock_qdrant, mock_memgraph, mock_ollama, client: TestClient,
    ) -> None:
        """Error responses must not leak exception messages."""
        r = client.get("/ready")
        body = r.json()
        for svc_status in body["services"].values():
            assert svc_status == "error"
            assert "down" not in svc_status
            assert ":" not in svc_status

    @patch("metatron.api.routes.health._check_ollama")
    @patch("metatron.api.routes.health._check_memgraph")
    @patch("metatron.api.routes.health._check_qdrant", side_effect=Exception("qdrant down"))
    def test_ready_partial_degraded(
        self, mock_qdrant, mock_memgraph, mock_ollama, client: TestClient,
    ) -> None:
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["services"]["memgraph"] == "ok"
        assert body["services"]["qdrant"] == "error"


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

    def test_cors_explicit_with_credentials(self, client: TestClient) -> None:
        """With explicit origins, credentials are allowed."""
        r = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert r.headers.get("access-control-allow-credentials") == "true"

    def test_cors_wildcard_no_credentials(self) -> None:
        """With CORS_ORIGINS='*', credentials must be disabled."""
        app = create_app(Settings(METATRON_ENV="development"))
        c = TestClient(app)
        r = c.get("/health", headers={"Origin": "https://any-site.com"})
        assert r.headers.get("access-control-allow-origin") == "*"
        # Wildcard + credentials is invalid per CORS spec
        assert r.headers.get("access-control-allow-credentials") is None


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
        # Error detail must not leak exception internals
        assert "LLM error" not in r.json().get("detail", "")
        assert "Search failed" in r.json().get("detail", "")


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
        assert "event: done" in text

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer",
           side_effect=RuntimeError("LLM boom"))
    def test_stream_error_no_details(
        self, mock_search, mock_mgr, client: TestClient,
    ) -> None:
        """SSE error events must not leak exception messages."""
        mock_mgr.return_value.get_active_workspace.return_value = _DEFAULT_WS

        with client.stream("POST", "/api/v1/chat/stream", json={
            "question": "hello",
        }) as r:
            raw = b""
            for chunk in r.iter_bytes():
                raw += chunk

        text = raw.decode()
        assert "event: error" in text
        assert "LLM boom" not in text
        assert "Search failed" in text


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
        from metatron.api.routes.chat import split_into_sentences
        text = "First sentence. Second sentence. Third sentence here."
        chunks = split_into_sentences(text)
        assert len(chunks) >= 1
        # All text is preserved
        assert "".join(chunks).replace(" ", "") == text.replace(" ", "")

    def test_empty_string_returns_original(self) -> None:
        from metatron.api.routes.chat import split_into_sentences
        assert split_into_sentences("") == [""]

    def test_short_text_single_chunk(self) -> None:
        from metatron.api.routes.chat import split_into_sentences
        assert split_into_sentences("Hi.") == ["Hi."]


class TestSourceExtraction:
    def test_extracts_sources(self) -> None:
        from metatron.api.routes.chat import extract_sources_section
        answer = "The answer.\n\n\U0001f4da Sources:\n\U0001f4c4 Doc A\n\U0001f4cb Task B"
        body, sources = extract_sources_section(answer)
        assert body == "The answer."
        assert len(sources) == 2
        assert "\U0001f4c4 Doc A" in sources

    def test_no_sources_section(self) -> None:
        from metatron.api.routes.chat import extract_sources_section
        body, sources = extract_sources_section("Just an answer.")
        assert body == "Just an answer."
        assert sources == []
