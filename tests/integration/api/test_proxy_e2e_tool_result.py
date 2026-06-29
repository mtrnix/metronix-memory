"""Tool-result round appends entity-linked memory (MTRNIX-372 P4).

Integration test — requires Postgres + Neo4j (make docker-up + make migrate).

Seeds an Entity + a memory ABOUT it (PG content + Neo4j edge), then sends a
request whose tail message is a tool result mentioning that entity, and asserts
the appended memory reached the upstream body and the applied event fired.
Agent + memory are seeded directly (no JWT-gated endpoints).
"""

from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from metronix.agents.models import AgentRecord
from metronix.agents.persistence import AgentPersistence
from metronix.api.app import create_app
from metronix.core.config import Settings
from metronix.core.models import MemoryRecord
from metronix.proxy.upstream import UpstreamLLMClient
from metronix.storage import memory_graph

pytestmark = pytest.mark.integration

_ENTITY = "WidgetCorp"
_MEMORY = "WidgetCorp ships blue widgets to enterprise clients."

_CAPTURED: dict[str, bytes] = {}


def _fake_upstream(request: httpx.Request) -> httpx.Response:
    _CAPTURED["body"] = request.read()
    sse = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


def _seed_entity(ws: str, name: str) -> None:
    from metronix.storage.neo4j_graph import get_graph_driver

    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            "MERGE (e:Entity {name: $name, workspace_id: $ws})",
            {"name": name, "ws": ws},
        )


async def _seed_agent_and_memory(settings: Settings, ws: str) -> str:
    from sqlalchemy.ext.asyncio import create_async_engine

    from metronix.storage.memory_postgres import MemoryPostgresStore

    engine = create_async_engine(settings.postgres_dsn)
    repo = AgentPersistence(engine)
    agent = AgentRecord(
        workspace_id=ws,
        name=f"e2e-enricher-{uuid4().hex[:8]}",
        model="gpt-4o-mini",
        capabilities=["knowledge_base"],
        current_config={
            "upstream": {"provider": "openai", "model_name": "gpt-4o-mini", "api_key_ref": None}
        },
    )
    await repo.save_new(agent)

    record = MemoryRecord(workspace_id=ws, agent_id=agent.id, content=_MEMORY, source_type="test")
    await MemoryPostgresStore(engine).save(record)
    await engine.dispose()

    # Neo4j: Entity must pre-exist (link MATCHes it), then create node + ABOUT edge.
    _seed_entity(ws, _ENTITY)
    memory_graph.save_memory_to_graph(record, entity_names=[_ENTITY])
    return agent.id


async def test_tool_result_appends_memory() -> None:
    settings = Settings(
        METRONIX_OPENAI_COMPAT_KEY="k",
        METRONIX_PROXY_ENABLED=True,
        METRONIX_PROXY_TOOL_RESULT_ENRICHMENT=True,
        METRONIX_PROXY_DEFAULT_UPSTREAM_KEY="sk-e2e",
    )
    ws = settings.default_workspace_id
    agent_id = await _seed_agent_and_memory(settings, ws)

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
                "messages": [
                    {"role": "user", "content": "look up the client"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "t1", "function": {"name": "lookup"}}],
                    },
                    {"role": "tool", "content": f"Found record for {_ENTITY}."},
                ],
            },
        )
        assert resp.status_code == 200
        corr = resp.headers["x-metronix-correlation-id"]
        _ = resp.text  # drain the stream so the generator finishes

    # The appended memory must have reached the upstream system message.
    assert _MEMORY.encode() in _CAPTURED["body"]

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
    assert "proxy.tool_result_enrichment.applied" in types
