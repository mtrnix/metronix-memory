"""SSE event helper functions for the ASOC chat endpoint (MTRNIX-354, T4).

Every function returns a dict with ``event`` and ``data`` keys that
``sse_starlette.EventSourceResponse`` will format as a proper SSE event.

Event types (Confluence §6):
    status   — pipeline phase update (``{"status": "<phase>"}``).
    chunk    — LLM text delta (``{"text": "<delta>"}``).
    sources  — structured citation list (``{"sources": [...]}``)
    tool_call — MCP tool execution update.
    done     — terminal event, always last (``{"workspace_id": ..., "thread_id": ...}``).
    error    — terminal error event, always followed by exactly one ``done``.
"""

from __future__ import annotations

import json


def sse_status(status: str) -> dict[str, str]:
    """Pipeline phase status event — emitted before each major stage."""
    return {"event": "status", "data": json.dumps({"status": status})}


def sse_chunk(text: str) -> dict[str, str]:
    """LLM streaming text delta event."""
    return {"event": "chunk", "data": json.dumps({"text": text})}


def sse_sources(citations: list[dict]) -> dict[str, str]:  # type: ignore[type-arg]
    """Structured citation list emitted after the LLM stream completes."""
    return {"event": "sources", "data": json.dumps({"sources": citations})}


def sse_tool_call(tool: str, status: str, *, reason: str | None = None) -> dict[str, str]:
    """MCP tool call lifecycle event (``running`` / ``done`` / ``error``)."""
    payload: dict[str, str] = {"tool": tool, "status": status}
    if reason is not None:
        payload["reason"] = reason
    return {"event": "tool_call", "data": json.dumps(payload)}


def sse_done(workspace_id: str, thread_id: str | None) -> dict[str, str]:
    """Terminal event — always the last event in the stream."""
    return {
        "event": "done",
        "data": json.dumps({"workspace_id": workspace_id, "thread_id": thread_id}),
    }


def sse_error(code: str, message: str) -> dict[str, str]:
    """Error event — always followed by a ``done`` event."""
    return {"event": "error", "data": json.dumps({"code": code, "message": message})}
