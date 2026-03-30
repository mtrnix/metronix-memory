"""Tests for OpenAI-compatible API endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.workspaces.models import Workspace


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        DEFAULT_WORKSPACE_ID="TEST_WS",
        DEFAULT_WORKSPACE_NAME="Test Workspace",
        METATRON_OPENAI_COMPAT_ENABLED=True,
        METATRON_OPENAI_COMPAT_KEY="test-key-123",
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


_TEST_WS = Workspace(
    workspace_id="TEST_WS",
    name="Test Workspace",
    user_id="system",
    is_active=True,
)


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


class TestModelsEndpoint:
    """GET /v1/models"""

    @patch("metatron.workspaces.get_workspace_manager")
    def test_list_models_returns_workspaces(self, mock_mgr, client):
        mock_mgr.return_value.list_workspaces.return_value = [_TEST_WS]
        r = client.get("/v1/models", headers={"Authorization": "Bearer test-key-123"})
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "metatron-rag-TEST_WS"
        assert data["data"][0]["owned_by"] == "metatron"

    def test_list_models_no_auth_returns_401(self, client):
        r = client.get("/v1/models")
        assert r.status_code == 401

    def test_list_models_wrong_key_returns_401(self, client):
        r = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
        assert r.status_code == 401

    def test_list_models_disabled_returns_404(self):
        settings = Settings(
            METATRON_ENV="development",
            METATRON_OPENAI_COMPAT_KEY="test-key",
            METATRON_OPENAI_COMPAT_ENABLED=False,
        )
        app = create_app(settings)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
        assert r.status_code == 404

    def test_list_models_no_key_configured_returns_401(self):
        """When METATRON_OPENAI_COMPAT_KEY is empty and no api_key_store, returns 401."""
        settings = Settings(
            METATRON_ENV="development",
            METATRON_OPENAI_COMPAT_KEY="",
            METATRON_OPENAI_COMPAT_ENABLED=True,
        )
        app = create_app(settings)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/models", headers={"Authorization": "Bearer anything"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/chat/completions (non-streaming)
# ---------------------------------------------------------------------------


class TestChatCompletions:
    """POST /v1/chat/completions"""

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock)
    def test_non_streaming_returns_openai_format(self, mock_search, mock_mgr, client):
        mock_mgr.return_value.get_workspace.return_value = _TEST_WS
        mock_search.return_value = "The answer is 42."

        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-TEST_WS",
                "messages": [{"role": "user", "content": "What is the answer?"}],
                "stream": False,
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "chat.completion"
        assert data["model"] == "metatron-rag-TEST_WS"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert "42" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "stop"

    @patch("metatron.workspaces.get_workspace_manager")
    def test_unknown_model_returns_404(self, mock_mgr, client):
        mock_mgr.return_value.get_workspace.return_value = None
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-NONEXISTENT",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert r.status_code == 404
        assert "error" in r.json()

    def test_empty_messages_returns_400(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={"model": "metatron-rag-TEST_WS", "messages": []},
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert r.status_code == 400

    @patch("metatron.workspaces.get_workspace_manager")
    def test_no_user_message_returns_400(self, mock_mgr, client):
        mock_mgr.return_value.get_workspace.return_value = _TEST_WS
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-TEST_WS",
                "messages": [{"role": "system", "content": "You are a bot"}],
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert r.status_code == 400

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock)
    def test_sources_converted_to_markdown_links(self, mock_search, mock_mgr, client):
        mock_mgr.return_value.get_workspace.return_value = _TEST_WS
        mock_search.return_value = (
            "Answer here.\n\n\U0001f4da Sources:\n"
            "\U0001f4c4 Doc Title \u2014 https://example.com/doc\n"
            "\U0001f4cb JIRA-123 \u2014 https://jira.example.com/JIRA-123"
        )
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-TEST_WS",
                "messages": [{"role": "user", "content": "test"}],
                "stream": False,
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        content = r.json()["choices"][0]["message"]["content"]
        assert "[\U0001f4c4 Doc Title](https://example.com/doc)" in content
        assert "[\U0001f4cb JIRA-123](https://jira.example.com/JIRA-123)" in content

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock)
    def test_extra_openai_params_ignored(self, mock_search, mock_mgr, client):
        """temperature, max_tokens etc. are accepted but ignored."""
        mock_mgr.return_value.get_workspace.return_value = _TEST_WS
        mock_search.return_value = "OK"
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-TEST_WS",
                "messages": [{"role": "user", "content": "test"}],
                "temperature": 0.5,
                "max_tokens": 100,
                "top_p": 0.9,
                "frequency_penalty": 0.1,
                "stream": False,
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/chat/completions (streaming)
# ---------------------------------------------------------------------------


class TestChatCompletionsStreaming:
    """POST /v1/chat/completions with stream=true"""

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock)
    def test_streaming_returns_sse_chunks(self, mock_search, mock_mgr, client):
        mock_mgr.return_value.get_workspace.return_value = _TEST_WS
        mock_search.return_value = "The answer is 42."

        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-TEST_WS",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        # Parse SSE events
        lines = r.text.strip().split("\n")
        data_lines = [line for line in lines if line.startswith("data: ")]
        assert len(data_lines) >= 2  # at least one content chunk + [DONE]
        assert data_lines[-1] == "data: [DONE]"

        # First data chunk should have role
        first = json.loads(data_lines[0][6:])
        assert first["choices"][0]["delta"]["role"] == "assistant"

        # Last data chunk before [DONE] should have finish_reason=stop
        last_chunk = json.loads(data_lines[-2][6:])
        assert last_chunk["choices"][0]["finish_reason"] == "stop"

    @patch("metatron.workspaces.get_workspace_manager")
    @patch("metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock)
    def test_streaming_includes_sources_as_markdown(self, mock_search, mock_mgr, client):
        mock_mgr.return_value.get_workspace.return_value = _TEST_WS
        mock_search.return_value = (
            "Answer.\n\n\U0001f4da Sources:\n\U0001f4c4 Doc \u2014 https://example.com"
        )
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "metatron-rag-TEST_WS",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
            headers={"Authorization": "Bearer test-key-123"},
        )
        # Collect all content from delta chunks
        full_text = ""
        for line in r.text.strip().split("\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                chunk = json.loads(line[6:])
                content = chunk["choices"][0]["delta"].get("content", "")
                full_text += content
        assert "[\U0001f4c4 Doc](https://example.com)" in full_text
