"""Proxy event constants + payload (PROJ-372 P3)."""

from dataclasses import asdict

from metronix.core.events import PROXY_CALL_COMPLETED
from metronix.proxy.events import (
    ALL_PROXY_EVENTS,
    PROXY_REQUEST_RECEIVED,
    PROXY_UPSTREAM_ERROR,
    ProxyCallCompletedPayload,
)


def test_core_constant_value() -> None:
    assert PROXY_CALL_COMPLETED == "proxy.call_completed"


def test_eleven_activity_event_types() -> None:
    assert len(ALL_PROXY_EVENTS) == 11
    assert PROXY_REQUEST_RECEIVED == "proxy.request.received"
    assert PROXY_UPSTREAM_ERROR == "proxy.upstream.error"
    # all unique
    assert len(set(ALL_PROXY_EVENTS)) == 11


def test_payload_roundtrip() -> None:
    p = ProxyCallCompletedPayload(
        correlation_id="c",
        workspace_id="WS",
        agent_id="A",
        upstream_provider="openai",
        upstream_model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=20,
        latency_ms=123,
        ttft_ms=45,
        finish_reason="stop",
        upstream_status=200,
        error_reason=None,
    )
    d = asdict(p)
    assert d["correlation_id"] == "c"
    assert d["upstream_status"] == 200
