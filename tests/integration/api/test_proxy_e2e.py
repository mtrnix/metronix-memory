"""E2E proxy call against a fake OAI upstream (MTRNIX-372 P3).

Integration test — requires Postgres running (make docker-up + make migrate).

The agent is seeded directly via AgentPersistence in the proxy's resolved
workspace (settings.default_workspace_id) and activity is read straight from
the ActivityStore, so the test exercises ONLY the proxy surface (static-key
auth) without the JWT-gated /api/v1/agents endpoints.
"""

from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from metatron.agents.models import AgentRecord
from metatron.agents.persistence import AgentPersistence
from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.proxy.upstream import UpstreamLLMClient

pytestmark = pytest.mark.integration


def _fake_upstream(request: httpx.Request) -> httpx.Response:
    sse = (
        b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
        b'data: {"usage":{"prompt_tokens":7,"completion_tokens":3}}\n\n'
        b"data: [DONE]\n\n"
    )
    return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


async def _seed_agent(settings: Settings, ws: str) -> str:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.postgres_dsn)
    repo = AgentPersistence(engine)
    agent = AgentRecord(
        workspace_id=ws,
        name=f"e2e-proxy-{uuid4().hex[:8]}",
        model="gpt-4o-mini",
        capabilities=["knowledge_base"],
        current_config={
            "upstream": {
                "provider": "openai",
                "model_name": "gpt-4o-mini",
                "api_key_ref": None,
            }
        },
    )
    await repo.save_new(agent)
    await engine.dispose()
    return agent.id


async def test_proxy_e2e_stream() -> None:
    settings = Settings(
        METATRON_OPENAI_COMPAT_KEY="k",
        METATRON_PROXY_ENABLED=True,
        METATRON_PROXY_DEFAULT_UPSTREAM_KEY="sk-e2e",
    )
    ws = settings.default_workspace_id
    agent_id = await _seed_agent(settings, ws)

    app = create_app(settings)
    app.state.upstream_llm_client = UpstreamLLMClient(
        timeout=5.0, transport=httpx.MockTransport(_fake_upstream)
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
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
        assert resp.headers.get("x-metronix-agent-id") == agent_id
        corr = resp.headers["x-metronix-correlation-id"]
        assert corr
        text = resp.text
        assert '"content":"answer"' in text
        assert text.rstrip().endswith("[DONE]")

    # Verify the per-call activity trace directly via the store.
    store = app.state.activity_store
    rows = await store.list_for_agent(
        workspace_id=ws,
        agent_id=agent_id,
        since=None,
        until=None,
        event_types=None,
        session_id=None,
        correlation_id=corr,
        limit=50,
        offset=0,
    )
    types = {r["event_type"] for r in rows}
    assert "proxy.request.received" in types
    assert "proxy.upstream.dispatched" in types
    assert "proxy.upstream.completed" in types
