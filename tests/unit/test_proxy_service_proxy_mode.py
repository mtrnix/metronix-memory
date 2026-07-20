"""ProxyService proxy-mode dispatch (PROJ-372 P3)."""

import asyncio
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


def _make_service(
    agent: AgentRecord,
    frames: list[bytes],
    *,
    conversation_events: MagicMock | None = None,
    compaction: MagicMock | None = None,
    settings: Settings | None = None,
    stream_error: Exception | None = None,
):
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
        if stream_error is not None:
            raise stream_error

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
        settings=settings or Settings(),
        activity_logger_factory=lambda ws: activity,
        conversation_events=conversation_events,
        compaction=compaction,
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


async def test_completed_stream_captures_exchange_in_background() -> None:
    """Conversation persistence happens after the SSE bytes have been forwarded."""
    frames = [
        b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    event_store = MagicMock()
    event_store.append_event = AsyncMock()
    svc, _bus, activity = _make_service(
        _agent({"provider": "openai", "model_name": "m"}),
        frames,
        conversation_events=event_store,
    )
    response = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "conversation_id": "session-1",
            "messages": [{"role": "user", "content": "question"}],
        },
        mode="proxy",
    )

    body = b"".join([chunk async for chunk in response.body_iterator])
    assert b'"content":"answer"' in body
    await asyncio.sleep(0)

    assert event_store.append_event.await_count == 2
    captured = [call.args[0] for call in event_store.append_event.await_args_list]
    assert [(event.role, event.content) for event in captured] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]
    activity.log.assert_any_await(
        agent_id="A",
        event_type="conversation.events.captured",
        correlation_id=activity.log.await_args_list[-1].kwargs["correlation_id"],
        session_id="session-1",
        data={"event_count": 2, "automatic_compacted": False},
    )


async def test_completed_stream_captures_assistant_json_split_across_chunks() -> None:
    """Capture parses complete CRLF-framed SSE events, not transport chunks."""
    content_frame = b'data: {"choices":[{"delta":{"content":"split answer"}}]}\r\n\r\n'
    frames = [content_frame[:35], content_frame[35:], b"data: [DONE]\r\n\r\n"]
    event_store = MagicMock()
    event_store.append_event = AsyncMock()
    svc, _bus, _activity = _make_service(
        _agent({"provider": "openai", "model_name": "m"}),
        frames,
        conversation_events=event_store,
    )
    response = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "conversation_id": "session-1",
            "messages": [{"role": "user", "content": "question"}],
        },
        mode="proxy",
    )

    body = b"".join([chunk async for chunk in response.body_iterator])
    await asyncio.sleep(0)

    assert body == b"".join(frames)
    captured = [call.args[0] for call in event_store.append_event.await_args_list]
    assert [(event.role, event.content) for event in captured] == [
        ("user", "question"),
        ("assistant", "split answer"),
    ]


async def test_completed_stream_never_automatically_compacts_when_feature_enabled() -> None:
    """Capture only persists raw events until the store supports an atomic claim/ack."""
    frames = [
        b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    event_store = MagicMock()
    event_store.append_event = AsyncMock()
    # This makes the pre-fix ledger check take the unsafe compaction branch.
    event_store.get_ledger = AsyncMock(return_value=None)
    compaction = MagicMock()
    compaction.maybe_compact = AsyncMock()
    svc, _bus, _activity = _make_service(
        _agent({"provider": "openai", "model_name": "m"}),
        frames,
        conversation_events=event_store,
        compaction=compaction,
        settings=Settings(METRONIX_CONVERSATION_COMPACTION_ENABLED=True),
    )

    response = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "conversation_id": "session-1",
            "messages": [{"role": "user", "content": "question"}],
        },
        mode="proxy",
    )

    _ = b"".join([chunk async for chunk in response.body_iterator])
    await asyncio.sleep(0)

    event_store.append_event.assert_awaited()
    compaction.maybe_compact.assert_not_awaited()


async def test_failed_stream_does_not_capture_conversation() -> None:
    """A synthesized SSE error does not turn a partial exchange into retained events."""
    event_store = MagicMock()
    event_store.append_event = AsyncMock()
    svc, _bus, _activity = _make_service(
        _agent({"provider": "openai", "model_name": "m"}),
        [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'],
        conversation_events=event_store,
        stream_error=RuntimeError("upstream interrupted"),
    )

    response = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "conversation_id": "session-1",
            "messages": [{"role": "user", "content": "question"}],
        },
        mode="proxy",
    )

    body = b"".join([chunk async for chunk in response.body_iterator])
    await asyncio.sleep(0)

    assert b'"type": "upstream_error"' in body
    event_store.append_event.assert_not_awaited()


async def test_premature_2xx_eof_does_not_capture_conversation() -> None:
    """A clean EOF before the terminal SSE marker is not a completed exchange."""
    partial = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
    event_store = MagicMock()
    event_store.append_event = AsyncMock()
    svc, _bus, activity = _make_service(
        _agent({"provider": "openai", "model_name": "m"}),
        [partial],
        conversation_events=event_store,
    )

    response = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "conversation_id": "session-1",
            "messages": [{"role": "user", "content": "question"}],
        },
        mode="proxy",
    )

    body = b"".join([chunk async for chunk in response.body_iterator])
    await asyncio.sleep(0)

    assert body == partial
    event_store.append_event.assert_not_awaited()
    assert "conversation.events.captured" not in [
        call.kwargs["event_type"] for call in activity.log.await_args_list
    ]
