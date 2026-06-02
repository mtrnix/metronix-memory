"""Tool-result round appends entity memories (MTRNIX-372 P4).

Integration test — requires Postgres + Neo4j + Qdrant.
"""

import asyncio

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.core.models import MemoryRecord

pytestmark = pytest.mark.integration


def _fake_upstream(request: httpx.Request) -> httpx.Response:
    """Capture the enriched messages the proxy sends upstream."""
    _fake_upstream.last_body = request.read()
    sse = (
        b'data: {"choices":[{"delta":{"content":"done"}}]}\n\n'
        b'data: {"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\n'
        b"data: [DONE]\n\n"
    )
    return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


_fake_upstream.last_body = b""  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_capture():
    _fake_upstream.last_body = b""


async def test_tool_result_appends_memory() -> None:
    settings = Settings(
        METATRON_OPENAI_COMPAT_KEY="k",
        METATRON_PROXY_ENABLED=True,
        METATRON_PROXY_DEFAULT_UPSTREAM_KEY="sk-e2e",
    )
    app = create_app(settings)

    # Wire fake upstream
    from metatron.proxy.upstream import UpstreamLLMClient

    fake_client = UpstreamLLMClient(
        timeout=5.0, transport=httpx.MockTransport(_fake_upstream)
    )
    app.state.upstream_llm_client = fake_client

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        # 1. Create a proxy agent
        create_resp = await client.post(
            "/api/v1/agents",
            json={
                "name": "e2e-enricher",
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

        # 2. Store a memory ABOUT a known entity via the memory API
        #    We save directly to Neo4j via memory_graph to create the ABOUT edge.
        from metatron.storage.memory_graph import save_memory_to_graph

        ws = create_resp.json()["workspace_id"]
        rec = MemoryRecord(
            id="mem-enrich-test",
            workspace_id=ws,
            agent_id=agent_id,
            content="WidgetCorp is a key supplier of titanium parts",
        )
        await asyncio.to_thread(
            save_memory_to_graph, rec, entity_names=["WidgetCorp"]
        )

        # Invalidate the entity trie so it picks up the new entity
        trie = getattr(app.state, "entity_trie", None)
        if trie is not None:
            trie.invalidate(ws)

        # 3. Send a tool-result round mentioning the entity
        resp = await client.post(
            "/v1/proxy/chat/completions",
            headers={
                "Authorization": "Bearer k",
                "X-Agent-Id": agent_id,
            },
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [
                    {"role": "user", "content": "check suppliers"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "t1"}],
                    },
                    {
                        "role": "tool",
                        "content": "WidgetCorp reported a delay in shipment",
                    },
                ],
            },
        )
        assert resp.status_code == 200

        # 4a. The upstream should have received the appended memory
        body = _fake_upstream.last_body.decode("utf-8", errors="replace")
        assert "WidgetCorp is a key supplier" in body

        # 4b. Activity log should contain proxy.tool_result_enrichment.applied
        corr = resp.headers.get("x-metronix-correlation-id")
        if corr:
            activity_resp = await client.get(
                f"/api/v1/agents/{agent_id}/activity",
                params={"correlation_id": corr},
            )
            assert activity_resp.status_code == 200
            events = activity_resp.json().get("events", [])
            types = {e["event_type"] for e in events}
            assert "proxy.tool_result_enrichment.applied" in types
