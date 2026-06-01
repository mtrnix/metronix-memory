"""Proxy route contract (MTRNIX-372 P3). Uses TestClient."""

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.core.config import Settings


@pytest.fixture
def client():
    settings = Settings(
        METATRON_OPENAI_COMPAT_KEY="test-key",
        METATRON_PROXY_ENABLED=True,
    )
    app = create_app(settings)
    return TestClient(app)


def test_proxy_requires_x_agent_id(client: TestClient) -> None:
    resp = client.post(
        "/v1/proxy/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 400
    assert "x_agent_id_required" in resp.text


def test_proxy_bad_key_401(client: TestClient) -> None:
    resp = client.post(
        "/v1/proxy/chat/completions",
        headers={"Authorization": "Bearer wrong", "X-Agent-Id": "A"},
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


def test_proxy_disabled_404() -> None:
    settings = Settings(
        METATRON_OPENAI_COMPAT_KEY="k",
        METATRON_PROXY_ENABLED=False,
    )
    app = create_app(settings)
    c = TestClient(app)
    resp = c.post(
        "/v1/proxy/chat/completions",
        headers={"Authorization": "Bearer k", "X-Agent-Id": "A"},
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
    )
    # Route not mounted → either 404 (no auth middleware) or 401 (auth middleware
    # intercepts before FastAPI routing). Both confirm the proxy is not serving.
    assert resp.status_code in (401, 404)
