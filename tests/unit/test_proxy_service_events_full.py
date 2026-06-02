"""Remaining proxy events: query_rewritten, tool_call_observed, client_cancelled.

MTRNIX-372 Task 27.
"""

from unittest.mock import AsyncMock, MagicMock

from metatron.agents.models import AgentRecord
from metatron.core.config import Settings
from metatron.core.models import AssembledContext
from metatron.proxy.events import ALL_PROXY_EVENTS
from metatron.proxy.service import ProxyService
from metatron.proxy.upstream import ProxyStreamFrame


def _service_with_tool_call() -> ProxyService:
    agent_service = AsyncMock()
    agent_service.get_agent.return_value = AgentRecord(
        id="A", workspace_id="WS", name="a", capabilities=[],
        current_config={"upstream": {"provider": "openai", "model_name": "m"}},
    )
    assembler = AsyncMock()
    assembler.assemble.return_value = AssembledContext(
        system_prompt="<relevant_memories>\n- x\n</relevant_memories>",
        sections={
            "constitution": "", "preferences": "",
            "relevant_memories": "- x", "relevant_knowledge": "",
        },
        correlation_id="c",
    )

    tool_call_frame = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"id":"t1","function":{"name":"f"}}]}}]}\n\n'
    )

    async def _stream(**kwargs):
        yield ProxyStreamFrame(raw=tool_call_frame, status=200)
        yield ProxyStreamFrame(
            raw=b'data: {"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\n'
        )
        yield ProxyStreamFrame(raw=b"data: [DONE]\n\n")

    upstream = MagicMock()
    upstream.stream = _stream
    creds = AsyncMock()
    creds.resolve.return_value = "k"
    activity = AsyncMock()
    return ProxyService(
        assembler=assembler, upstream_client=upstream, credentials=creds,
        agent_service=agent_service, event_bus=AsyncMock(), settings=Settings(),
        activity_logger_factory=lambda ws: activity,
    ), activity


async def test_tool_call_observed_emitted() -> None:
    svc, activity = _service_with_tool_call()
    resp = await svc.dispatch(
        agent_id="A", workspace_id="WS",
        request_body={
            "model": "m", "stream": True,
            "messages": [{"role": "user", "content": "q"}],
        },
        mode="proxy",
    )
    _ = b"".join([c async for c in resp.body_iterator])
    types = [c.kwargs["event_type"] for c in activity.log.await_args_list]
    assert "proxy.tool_call_observed" in types


async def test_query_rewritten_emitted() -> None:
    svc, activity = _service_with_tool_call()
    resp = await svc.dispatch(
        agent_id="A", workspace_id="WS",
        request_body={
            "model": "m", "stream": True,
            "messages": [{"role": "user", "content": "q"}],
        },
        mode="proxy",
    )
    _ = b"".join([c async for c in resp.body_iterator])
    types = [c.kwargs["event_type"] for c in activity.log.await_args_list]
    assert "proxy.query_rewritten" in types


def test_all_11_events_defined() -> None:
    """Sanity: all 11 proxy.* event types exist as constants."""
    assert len(ALL_PROXY_EVENTS) == 11
    assert len(set(ALL_PROXY_EVENTS)) == 11
