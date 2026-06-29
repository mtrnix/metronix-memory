"""ProxyService proxy-mode dispatch (PROJ-372 P3)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.agents.models import AgentRecord
from metronix.core.config import Settings
from metronix.core.models import AssembledContext
from metronix.proxy.service import AgentUpstreamNotConfiguredError, ProxyService
from metronix.proxy.upstream import ProxyStreamFrame


def _agent(upstream: dict | None) -> AgentRecord:
    cfg = {"upstream": upstream} if upstream is not None else {}
    return AgentRecord(
        id="A",
        workspace_id="WS",
        name="a",
        capabilities=["knowledge_base"],
        current_config=cfg,
    )


def _make_service(agent: AgentRecord, frames: list[bytes]):
    agent_service = AsyncMock()
    agent_service.get_agent.return_value = agent

    assembler = AsyncMock()
    assembler.assemble.return_value = AssembledContext(
        system_prompt="<preferences>\n- x\n</preferences>",
        sections={
            "constitution": "",
            "preferences": "- x",
            "relevant_memories": "",
            "relevant_knowledge": "",
        },
        correlation_id="c",
        degraded_sections=[],
        per_stage_ms={"memories": 1},
    )

    async def _stream(**kwargs):
        for b in frames:
            yield ProxyStreamFrame(raw=b, status=200)

    upstream_client = MagicMock()
    upstream_client.stream = _stream

    creds = AsyncMock()
    creds.resolve.return_value = "sk-test"

    bus = AsyncMock()
    activity = AsyncMock()

    svc = ProxyService(
        assembler=assembler,
        upstream_client=upstream_client,
        credentials=creds,
        agent_service=agent_service,
        event_bus=bus,
        settings=Settings(),
        activity_logger_factory=lambda ws: activity,
    )
    return svc, bus, activity


async def test_missing_upstream_raises() -> None:
    svc, _bus, _act = _make_service(_agent(None), [])
    with pytest.raises(AgentUpstreamNotConfiguredError):
        await svc.dispatch(
            agent_id="A",
            workspace_id="WS",
            request_body={
                "model": "m",
                "messages": [{"role": "user", "content": "hi"}],
            },
            mode="proxy",
        )


async def test_proxy_dispatch_streams_and_emits() -> None:
    frames = [
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    svc, bus, activity = _make_service(_agent({"provider": "openai", "model_name": "m"}), frames)
    resp = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
        mode="proxy",
    )
    body = b"".join([chunk async for chunk in resp.body_iterator])
    assert b'"content":"hi"' in body
    # PROXY_CALL_COMPLETED emitted once
    emitted = [c.args[0] for c in bus.emit.await_args_list]
    assert "proxy.call_completed" in emitted
    # activity got request.received + upstream.dispatched + upstream.completed
    types = [c.kwargs["event_type"] for c in activity.log.await_args_list]
    assert "proxy.request.received" in types
    assert "proxy.upstream.dispatched" in types
    assert "proxy.upstream.completed" in types
