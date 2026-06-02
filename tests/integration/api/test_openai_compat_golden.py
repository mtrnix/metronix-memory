"""Golden-file SSE shape for legacy /v1/chat/completions (MTRNIX-372 P3 gate).

Integration test — requires Postgres + workspace. Validates that the
legacy handler output structure does not change across refactors.
"""

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.proxy.upstream import UpstreamLLMClient

pytestmark = pytest.mark.integration


def test_legacy_stream_structure(monkeypatch) -> None:
    """A-full rag delegation preserves the legacy SSE shape + citation rendering.

    hybrid_search_and_answer is mocked so the test is deterministic and needs no
    live LLM; it exercises ProxyService.dispatch(mode=rag) -> build_rag_stream ->
    _stream_response end to end.
    """

    async def _fake_answer(**kwargs):
        return "Hello world. [$[Doc A]$]\n\n---\n**Sources:**\n- 📄 Doc A — http://a"

    monkeypatch.setattr(
        "metatron.retrieval.search.hybrid_search_and_answer", _fake_answer
    )

    settings = Settings(METATRON_OPENAI_COMPAT_KEY="k", METATRON_PROXY_ENABLED=True)
    app = create_app(settings)
    # Lifespan is not run under TestClient(no-with); the rag path does not use the
    # upstream client but the builder constructs ProxyService with it, so provide one.
    app.state.upstream_llm_client = UpstreamLLMClient(timeout=5.0)
    client = TestClient(app)
    # MTRNIX is the default workspace and exists after migrations.
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={
            "model": "metatron-rag-MTRNIX",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    body = resp.text
    # Shape contract preserved across the A-full refactor (the exact citation
    # rendering is covered by legacy unit tests; here we lock the SSE envelope).
    assert '"object": "chat.completion.chunk"' in body
    assert '"role": "assistant"' in body
    assert body.rstrip().endswith("[DONE]")


def test_legacy_bad_workspace_returns_404() -> None:
    """A-full delegation must preserve the workspace-existence 404 (MTRNIX-372)."""
    settings = Settings(METATRON_OPENAI_COMPAT_KEY="k", METATRON_PROXY_ENABLED=True)
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
    settings = Settings(METATRON_OPENAI_COMPAT_KEY="k", METATRON_PROXY_ENABLED=True)
    client = TestClient(create_app(settings))
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={"model": "metatron-rag-DEFAULT", "stream": True, "messages": []},
    )
    assert resp.status_code == 400
