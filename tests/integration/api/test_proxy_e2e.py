"""E2E proxy call against a fake OAI upstream (MTRNIX-372 P3).

Integration test — requires Postgres running (make docker-up + make migrate).
"""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from metatron.api.app import create_app
from metatron.core.config import Settings

pytestmark = pytest.mark.integration


def _fake_upstream(request: httpx.Request) -> httpx.Response:
    sse = (
        b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
        b'data: {"usage":{"prompt_tokens":7,"completion_tokens":3}}\n\n'
        b"data: [DONE]\n\n"
    )
    return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


async def test_proxy_e2e_stream() -> None:
    settings = Settings(
        METATRON_OPENAI_COMPAT_KEY="k",
        METATRON_PROXY_ENABLED=True,
        METATRON_PROXY_DEFAULT_UPSTREAM_KEY="sk-e2e",
    )
    app = create_app(settings)

    # Override the upstream client to use a fake transport
    from metatron.proxy.upstream import UpstreamLLMClient

    fake_client = UpstreamLLMClient(timeout=5.0, transport=httpx.MockTransport(_fake_upstream))
    app.state.upstream_llm_client = fake_client

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        # Create a proxy agent via the registry API
        create_resp = await client.post(
            "/api/v1/agents",
            json={
                "name": "e2e-proxy",
                "model": "gpt-4o-mini",
                "capabilities": ["knowledge_base"],
                "current_config": {
                    "upstream": {
                        "provider": "openai",
                        "model_name": "gpt-4o-mini",
                        "api_key_ref": None,
                    }
                },
            },
        )
        assert create_resp.status_code in (200, 201)
        agent_id = create_resp.json()["id"]

        # Streamed proxy call
        resp = await client.post(
            "/v1/proxy/chat/completions",
            headers={"Authorization": "Bearer k", "X-Agent-Id": agent_id},
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "what do we know?"}],
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("x-metronix-correlation-id")
        assert resp.headers.get("x-metronix-agent-id") == agent_id
        text = resp.text
        assert '"content":"answer"' in text

        # Check activity log
        corr = resp.headers["x-metronix-correlation-id"]
        activity_resp = await client.get(
            f"/api/v1/agents/{agent_id}/activity",
            params={"correlation_id": corr},
        )
        assert activity_resp.status_code == 200
        events = activity_resp.json().get("events", [])
        types = {e["event_type"] for e in events}
        assert "proxy.request.received" in types
        assert "proxy.upstream.dispatched" in types
