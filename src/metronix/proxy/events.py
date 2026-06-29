"""Proxy activity-log event types + PROXY_CALL_COMPLETED payload (MTRNIX-372).

The 11 event_type strings are written to agent_activity_log (free-string column).
Every proxy.* activity row also carries a correlation_id (D8).
"""

from __future__ import annotations

from dataclasses import dataclass

PROXY_REQUEST_RECEIVED = "proxy.request.received"
PROXY_QUERY_REWRITTEN = "proxy.query_rewritten"
PROXY_CONTEXT_ASSEMBLED = "proxy.context.assembled"
PROXY_ENRICHMENT_DEGRADED = "proxy.enrichment_degraded"
PROXY_TOOL_RESULT_ENRICHMENT_APPLIED = "proxy.tool_result_enrichment.applied"
PROXY_TOOL_RESULT_ENRICHMENT_SKIPPED = "proxy.tool_result_enrichment.skipped"
PROXY_UPSTREAM_DISPATCHED = "proxy.upstream.dispatched"
PROXY_UPSTREAM_COMPLETED = "proxy.upstream.completed"
PROXY_UPSTREAM_ERROR = "proxy.upstream.error"
PROXY_TOOL_CALL_OBSERVED = "proxy.tool_call_observed"
PROXY_CLIENT_CANCELLED = "proxy.client.cancelled"

ALL_PROXY_EVENTS: tuple[str, ...] = (
    PROXY_REQUEST_RECEIVED,
    PROXY_QUERY_REWRITTEN,
    PROXY_CONTEXT_ASSEMBLED,
    PROXY_ENRICHMENT_DEGRADED,
    PROXY_TOOL_RESULT_ENRICHMENT_APPLIED,
    PROXY_TOOL_RESULT_ENRICHMENT_SKIPPED,
    PROXY_UPSTREAM_DISPATCHED,
    PROXY_UPSTREAM_COMPLETED,
    PROXY_UPSTREAM_ERROR,
    PROXY_TOOL_CALL_OBSERVED,
    PROXY_CLIENT_CANCELLED,
)


@dataclass(frozen=True)
class ProxyCallCompletedPayload:
    correlation_id: str
    workspace_id: str
    agent_id: str
    upstream_provider: str
    upstream_model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    ttft_ms: int | None
    finish_reason: str | None
    upstream_status: int
    error_reason: str | None
