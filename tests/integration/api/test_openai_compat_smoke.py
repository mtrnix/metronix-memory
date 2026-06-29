"""OpenAI-compatible API integration smoke (MTRNIX-323 §4).

A single end-to-end smoke that exercises ``POST /v1/chat/completions``
through the full ``create_app`` factory. The unit suite at
``tests/unit/test_openai_compat.py`` covers individual code paths
with mocks; this test catches the failure modes those mocks can't:

* ``create_app`` wiring drift (router registration, middleware order,
  workspace lookup, OAI-compat key validation).
* ``hybrid_search_and_answer`` returning a body the OAI envelope can't
  parse (``extract_sources_section`` / source markdown rendering).
* Non-ASCII (Russian) request body crashing somewhere on the path.

Per MTRNIX-323 the test must hit a live LLM and live Qdrant/Neo4j
when reachable so the integration is actually validated. When any
of those services are unavailable in the test environment, the test
skips gracefully — never fails — so this stays runnable in
``make test-all`` on a developer laptop without a full stack.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.core.config import Settings

pytestmark = pytest.mark.integration


_WORKSPACE_ID = "MTRNIX"
_OAI_KEY = "smoke-key-mtrnix-323"


def _service_reachable(url: str, timeout: float = 1.5) -> bool:
    """Return True if a TCP connection to ``url`` opens within ``timeout``."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_up(host: str) -> bool:
    """Probe Ollama ``/api/tags`` with a short timeout."""
    try:
        resp = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


@pytest.fixture
def settings() -> Settings:
    """Settings configured for the live OAI-compat surface.

    Picks up live service URLs from the local environment (``OLLAMA_HOST``,
    ``QDRANT_HOST``, ``NEO4J_URI`` …) so the smoke runs against the same
    services ``make eval`` and the dev API use.
    """
    return Settings(
        METRONIX_ENV="development",
        DEFAULT_WORKSPACE_ID=_WORKSPACE_ID,
        DEFAULT_WORKSPACE_NAME=_WORKSPACE_ID,
        METRONIX_OPENAI_COMPAT_ENABLED=True,
        METRONIX_OPENAI_COMPAT_KEY=_OAI_KEY,
    )


@pytest.fixture
def live_services_or_skip(settings: Settings) -> None:
    """Skip the smoke when required live services are unreachable."""
    if settings.llm_provider == "ollama" and not _ollama_up(settings.ollama_host):
        pytest.skip(f"Ollama not reachable at {settings.ollama_host}; smoke skipped")

    qdrant_url = f"http://{settings.qdrant_host}:{settings.qdrant_http_port}"
    if not _service_reachable(qdrant_url):
        pytest.skip(f"Qdrant not reachable at {qdrant_url}; smoke skipped")

    if not _service_reachable(settings.neo4j_uri.replace("bolt://", "http://")):
        pytest.skip(f"Neo4j not reachable at {settings.neo4j_uri}; smoke skipped")


def test_chat_completions_smoke_returns_200_with_citations(
    settings: Settings,
    live_services_or_skip: None,  # noqa: ARG001 — fixture used for skip side-effect
) -> None:
    """End-to-end smoke: full ``/v1/chat/completions`` path, live RAG.

    Sends a non-ASCII (Russian) query so the smoke also exercises the
    UTF-8 path through the request body, the search pipeline, and the
    response envelope.
    """
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {_OAI_KEY}"},
            json={
                "model": f"metronix-rag-{_WORKSPACE_ID}",
                "messages": [
                    {"role": "user", "content": "Что такое Метатрон?"},
                ],
                "stream": False,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()

    # OpenAI-compatible envelope shape — what every OAI client expects.
    assert body["object"] == "chat.completion"
    assert body["model"] == f"metronix-rag-{_WORKSPACE_ID}"
    assert isinstance(body["choices"], list) and len(body["choices"]) == 1

    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["role"] == "assistant"

    content = choice["message"]["content"]
    assert isinstance(content, str) and content, "answer body must not be empty"

    # Citations: the OAI route renders sources as a "**Sources:**" footer
    # with markdown links. Live RAG over the MTRNIX workspace should
    # surface at least one source — if none survive, the smoke fails
    # because either retrieval returned nothing or the citation
    # rendering broke.
    assert "**Sources:**" in content, (
        f"expected '**Sources:**' footer in response body; first 500 chars: {content[:500]!r}"
    )
    assert "](http" in content, (
        "expected at least one markdown link [title](http...) in citations; "
        f"first 500 chars: {content[:500]!r}"
    )

    # Non-ASCII path didn't crash and the answer made it back as a string
    # with the expected structural pieces.
    assert "\n" in content or len(content) > 50
