"""X-Metronix-* response headers (MTRNIX-372)."""

from __future__ import annotations


def enrichment_status(degraded: list[str], *, requested: list[str]) -> str:
    """full = nothing degraded; skipped = all requested degraded; else partial."""
    if not degraded:
        return "full"
    requested_set = set(requested) or set(degraded)
    if requested_set and requested_set.issubset(set(degraded)):
        return "skipped"
    return "partial"


def metronix_headers(
    *,
    correlation_id: str,
    agent_id: str,
    enrichment: str,
    upstream_status: int | None,
) -> dict[str, str]:
    headers = {
        "X-Metronix-Correlation-Id": correlation_id,
        "X-Metronix-Agent-Id": agent_id,
        "X-Metronix-Enrichment": enrichment,
    }
    if upstream_status is not None:
        headers["X-Metronix-Upstream-Status"] = str(upstream_status)
    return headers
