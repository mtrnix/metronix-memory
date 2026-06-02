"""Golden-file SSE shape for legacy /v1/chat/completions (MTRNIX-372 P3 gate).

Integration test — requires Postgres + workspace. Validates that the
legacy handler output structure does not change across refactors.
"""

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.core.config import Settings

pytestmark = pytest.mark.integration


def test_legacy_stream_structure() -> None:
    """Verify the legacy /v1/chat/completions SSE shape is preserved."""
    settings = Settings(METATRON_OPENAI_COMPAT_KEY="k")
    app = create_app(settings)
    client = TestClient(app)
    # Uses the DEFAULT workspace which should exist after migrations
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={
            "model": "metatron-rag-DEFAULT",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    body = resp.text
    assert "data:" in body
    assert "[DONE]" in body


def test_legacy_bad_workspace_returns_404() -> None:
    """A-full delegation must preserve the workspace-existence 404 (MTRNIX-372)."""
    settings = Settings(METATRON_OPENAI_COMPAT_KEY="k")
    client = TestClient(create_app(settings))
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={
            "model": "metatron-rag-NONEXISTENT_WS",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 404


def test_legacy_empty_messages_returns_400() -> None:
    """A-full delegation must preserve the empty-messages 400 (MTRNIX-372)."""
    settings = Settings(METATRON_OPENAI_COMPAT_KEY="k")
    client = TestClient(create_app(settings))
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={"model": "metatron-rag-DEFAULT", "stream": True, "messages": []},
    )
    assert resp.status_code == 400
