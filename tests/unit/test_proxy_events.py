"""Proxy event constants + payload (MTRNIX-372 P3)."""

from dataclasses import asdict

from metatron.core.events import PROXY_CALL_COMPLETED
from metatron.proxy.events import (
    PROXY_CLIENT_CANCELLED,
    PROXY_CONTEXT_ASSEMBLED,
    PROXY_ENRICHMENT_DEGRADED,
    PROXY_QUERY_REWRITTEN,
    PROXY_REQUEST_RECEIVED,
    PROXY_TOOL_CALL_OBSERVED,
    PROXY_TOOL_RESULT_ENRICHMENT_APPLIED,
    PROXY_TOOL_RESULT_ENRICHMENT_SKIPPED,
    PROXY_UPSTREAM_COMPLETED,
    PROXY_UPSTREAM_DISPATCHED,
    PROXY_UPSTREAM_ERROR,
    ALL_PROXY_EVENTS,
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
        correlation_id="c", workspace_id="WS", agent_id="A",
        upstream_provider="openai", upstream_model="gpt-4o-mini",
        prompt_tokens=10, completion_tokens=20, latency_ms=123,
        ttft_ms=45, finish_reason="stop", upstream_status=200, error_reason=None,
    )
    d = asdict(p)
    assert d["correlation_id"] == "c"
    assert d["upstream_status"] == 200
