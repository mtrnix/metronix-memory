"""ASOC Chat Orchestrator — composing T3+T5+T6+retrieval+LLM (MTRNIX-354, T4).

Sequence (per request):
    1. Derive workspace_id from ASOC JWT project_id.
    2. Check bootstrap_state (T2) — reject with SSE error if not READY.
    3. Rate-limit check via InMemoryTokenBucket.
    4. Get-or-create chat thread (T3 ChatPersistence).
    5. Apply asyncio.timeout for the full request.
    6. Run retrieval (hybrid_search_and_answer, stop_at="merged").
    7. Visibility filter (T5 AsocVisibilityFilter) — hard-fail on error.
    8. Fetch MCP tools (T6 AsocMcpClient) — graceful degradation on error.
    9. Build system prompt + history + context (asoc_prompt).
    10. Persist user message.
    11. Streaming LLM loop with tool-call accumulation.
    12. Process tool calls (cite_source builtin + ASOC MCP tools).
    13. Emit sources SSE event.
    14. Persist assistant message.
    15. Emit done SSE event.

Invariants:
    - ``done`` is ALWAYS the last event (success, error, or timeout).
    - ``error`` is always followed by exactly one ``done``.
    - No writes happen after a terminal event.
    - Tool-call loop is bounded by settings.chat_max_tool_calls_per_request.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import structlog

from metatron.chat.asoc_prompt import assemble_context, assemble_history, build_system_prompt
from metatron.chat.asoc_sse import (
    sse_chunk,
    sse_done,
    sse_error,
    sse_sources,
    sse_status,
    sse_tool_call,
)
from metatron.integrations.asoc_mcp_client import (
    AsocMcpError,
    McpAuthError,
    McpProtocolError,
    McpUnavailableError,
    ToolNotAllowedError,
)
from metatron.integrations.asoc_visibility import VisibilityFilterError
from metatron.llm.asoc_chat_provider import (
    LlmAuthError,
    LlmRateLimitError,
    LlmUnavailableError,
)
from metatron.workspaces.bootstrap.models import BootstrapStateEnum

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request

    from metatron.auth.asoc_session import AsocAuthContext
    from metatron.chat.asoc_rate_limit import InMemoryTokenBucket
    from metatron.chat.models import ChatThread
    from metatron.chat.persistence import ChatPersistence
    from metatron.core.config import Settings
    from metatron.integrations.asoc_mcp_client import AsocMcpClient, AsocToolDescriptor
    from metatron.integrations.asoc_visibility import AsocVisibilityFilter
    from metatron.llm.asoc_chat_provider import AsocStreamingChatProvider
    from metatron.workspaces.bootstrap.store import BootstrapStateStore

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# cite_source built-in tool schema (local to orchestrator)
# ---------------------------------------------------------------------------

CITE_SOURCE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cite_source",
        "description": (
            "Cite a source for a factual claim. "
            "Call this every time you reference information from the context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "anchor": {
                    "type": "string",
                    "description": "Marker [N] used in the answer.",
                },
                "source_type": {
                    "type": "string",
                    "enum": [
                        "issue",
                        "comment",
                        "issue_history",
                        "scan_result",
                        "layer",
                        "sbom",
                        "dependency",
                        "project",
                        "quality_gate",
                        "gate",
                        "event",
                    ],
                },
                "entity_id": {"type": "string"},
                "display_id": {"type": "string"},
                "title": {"type": "string"},
                "url_hint": {"type": "string"},
            },
            "required": ["anchor", "source_type", "entity_id"],
        },
    },
}


def _mcp_to_openai_tool(t: AsocToolDescriptor) -> dict[str, Any]:
    """Convert an :class:`AsocToolDescriptor` to an OpenAI tool-call schema."""
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema or {"type": "object", "properties": {}},
        },
    }


# ---------------------------------------------------------------------------
# Request body model (defined here to avoid circular import with routes)
# ---------------------------------------------------------------------------

# NOTE: The Pydantic request body model lives in the route file (asoc_chat.py)
# to keep FastAPI schema discovery simple. The orchestrator receives the
# already-validated body dict (or a Pydantic model with .message and .history).


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class AsocChatOrchestrator:
    """Stateless orchestrator — one instance shared across all requests.

    All mutable state is scoped to individual ``run()`` invocations.

    Args:
        persistence:            T3 ChatPersistence DAO.
        bootstrap_store:        T2 BootstrapStateStore DAO.
        asoc_visibility_filter: T5 AsocVisibilityFilter.
        asoc_mcp_client:        T6 AsocMcpClient.
        asoc_chat_provider:     Streaming LLM client.
        rate_limiter:           Per-user token bucket.
        settings:               App settings (read-only).
    """

    def __init__(
        self,
        persistence: ChatPersistence,
        bootstrap_store: BootstrapStateStore,
        asoc_visibility_filter: AsocVisibilityFilter,
        asoc_mcp_client: AsocMcpClient,
        asoc_chat_provider: AsocStreamingChatProvider,
        rate_limiter: InMemoryTokenBucket | None,
        settings: Settings,
    ) -> None:
        self._persistence = persistence
        self._bootstrap_store = bootstrap_store
        self._visibility_filter = asoc_visibility_filter
        self._mcp_client = asoc_mcp_client
        self._chat_provider = asoc_chat_provider
        # rate_limiter kept in ctor for backward-compat but is no longer used
        # inside run(). Rate-limiting now happens at the HTTP layer (route handler)
        # before EventSourceResponse opens, so clients see HTTP 429 instead of SSE error.
        self._rate_limiter = rate_limiter
        self._settings = settings

    async def run(
        self,
        auth: AsocAuthContext,
        body: Any,  # AsocChatRequest from routes — avoid import cycle
        request: Request,
    ) -> AsyncIterator[dict[str, str]]:
        """Entry point — yields SSE event dicts until ``done``.

        ``body.workspace_id`` is the fully qualified workspace ID supplied by the
        ASOC frontend in the request body (e.g. ``asoc-prod-<project_id>``).
        Phase 2a: workspace is no longer derived from a JWT claim.
        """
        workspace_id: str = body.workspace_id

        # T2 — workspace ready?
        state = await self._bootstrap_store.get(workspace_id)
        if state is None or state.state != BootstrapStateEnum.READY:
            yield sse_error("workspace_not_ready", "Workspace is not ready.")
            yield sse_done(workspace_id, None)
            return

        # Get-or-create thread (one per user in MVP).
        thread = await self._persistence.get_or_create_thread(workspace_id, auth.user_id)

        # Run under timeout.
        try:
            async with asyncio.timeout(self._settings.chat_timeout_seconds):
                async for ev in self._run_stream(auth, workspace_id, thread, body):
                    yield ev
        except TimeoutError:
            logger.warning(
                "asoc_chat.timeout",
                workspace_id=workspace_id,
                user_id=auth.user_id,
                timeout_seconds=self._settings.chat_timeout_seconds,
            )
            yield sse_error("timeout", "Request timed out.")
            yield sse_done(workspace_id, str(thread.thread_id))

    async def _run_stream(
        self,
        auth: AsocAuthContext,
        workspace_id: str,
        thread: ChatThread,
        body: Any,
    ) -> AsyncIterator[dict[str, str]]:
        """Inner generator — yields SSE events until ``done``."""
        from metatron.retrieval.search import hybrid_search_and_answer

        thread_id_str = str(thread.thread_id)

        # -- Retrieval --
        yield sse_status("searching")
        merged_results = await hybrid_search_and_answer(
            query=body.message,
            workspace_id=workspace_id,
            stop_at="merged",
            merged_limit=50,
        )

        # -- Visibility filter (hard-fail) --
        yield sse_status("filtering")
        try:
            filtered, _vstats = await self._visibility_filter.filter_chunks(
                auth.session_id, merged_results
            )
        except VisibilityFilterError as exc:
            logger.error(
                "asoc_chat.visibility_filter_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            yield sse_error("visibility_filter_failed", str(exc))
            yield sse_done(workspace_id, thread_id_str)
            return

        # -- MCP tools (graceful degradation on error) --
        yield sse_status("answering")
        try:
            mcp_tools = await self._mcp_client.list_available_tools(auth.session_id)
        except McpAuthError:
            yield sse_error("llm_unavailable", "MCP authentication failed.")
            yield sse_done(workspace_id, thread_id_str)
            return
        except Exception as exc:
            logger.warning("asoc_chat.mcp_tools_unavailable", error=str(exc))
            mcp_tools = []  # graceful degradation — retrieval-only mode

        # -- Prompt assembly --
        project_name = f"ASOC project {workspace_id}"  # MVP fallback
        system_prompt = build_system_prompt(project_name, mcp_tools)

        db_history = await self._persistence.list_messages(
            workspace_id,
            thread.thread_id,
            limit=self._settings.chat_history_turns_in_context * 2,
        )
        history_msgs = assemble_history(
            db_history,
            body.history,
            max_turns=self._settings.chat_history_turns_in_context,
            max_tokens=self._settings.chat_history_max_tokens_in_context,
        )
        context_text = assemble_context(filtered, self._settings.chat_context_max_chars)
        user_msg = f"{context_text}\n\nUser question: {body.message}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *history_msgs,
            {"role": "user", "content": user_msg},
        ]

        # Persist user message before streaming (ensures it's in history for retries).
        from metatron.chat.models import ChatMessageRole

        await self._persistence.append_message(
            workspace_id, thread.thread_id, ChatMessageRole.USER, body.message
        )

        # -- LLM availability check --
        if not self._chat_provider.is_available:
            yield sse_error("llm_unavailable", "LLM endpoint not configured.")
            yield sse_done(workspace_id, thread_id_str)
            return

        # -- Build tool schemas --
        mcp_tool_names: set[str] = {t.name for t in mcp_tools}
        tools: list[dict[str, Any]] = [
            CITE_SOURCE_TOOL,
            *(_mcp_to_openai_tool(t) for t in mcp_tools),
        ]

        # -- Streaming LLM loop --
        citations: list[dict[str, Any]] = []
        tool_calls_log: list[dict[str, Any]] = []
        assistant_content_parts: list[str] = []

        try:
            async for ev in self._llm_loop(
                auth,
                messages,
                tools,
                mcp_tool_names,
                citations,
                tool_calls_log,
                assistant_content_parts,
            ):
                yield ev
        except (LlmAuthError, LlmRateLimitError, LlmUnavailableError) as exc:
            yield sse_error("llm_unavailable", str(exc))
            yield sse_done(workspace_id, thread_id_str)
            return

        # -- Sources event --
        if citations:
            yield sse_sources(citations)

        # -- Persist assistant message --
        await self._persistence.append_message(
            workspace_id,
            thread.thread_id,
            ChatMessageRole.ASSISTANT,
            "".join(assistant_content_parts),
            citations_json=citations if citations else None,
            tool_calls_json=tool_calls_log if tool_calls_log else None,
        )

        yield sse_done(workspace_id, thread_id_str)

    async def _llm_loop(
        self,
        auth: AsocAuthContext,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        mcp_tool_names: set[str],
        citations: list[dict[str, Any]],
        tool_calls_log: list[dict[str, Any]],
        content_parts: list[str],
    ) -> AsyncIterator[dict[str, str]]:
        """Streaming LLM loop with tool-call accumulation.

        Yields SSE event dicts.  Raises ``LlmAuth/RateLimit/UnavailableError``
        on hard LLM failures.  Yields ``sse_error`` for soft failures (tool
        not allowed, unknown tool) and continues the loop.

        The loop is bounded by ``settings.chat_max_tool_calls_per_request``.
        """
        iterations = 0
        while True:
            if iterations >= self._settings.chat_max_tool_calls_per_request:
                yield sse_error("llm_unavailable", "tool_call_loop_exceeded")
                return
            iterations += 1

            # Accumulate tool-call deltas by index.
            pending: dict[int, dict[str, str]] = {}
            finish_reason: str | None = None

            async for delta in self._chat_provider.stream(messages, tools):
                if delta.content:
                    content_parts.append(delta.content)
                    yield sse_chunk(delta.content)

                if delta.tool_call_delta:
                    tcd = delta.tool_call_delta
                    entry = pending.setdefault(tcd.index, {"name": "", "arguments": "", "id": ""})
                    if tcd.id:
                        entry["id"] = tcd.id
                    if tcd.name:
                        entry["name"] = tcd.name
                    if tcd.arguments_delta:
                        entry["arguments"] += tcd.arguments_delta

                if delta.finish_reason:
                    finish_reason = delta.finish_reason
                    break

            if finish_reason == "stop" or not pending:
                return

            # Append assistant tool-call message.
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in pending.values()
                ],
            }
            messages.append(assistant_msg)

            # Process each tool call (sorted by index for stable ordering).
            for index in sorted(pending.keys()):
                tc = pending[index]
                tool_events = await self._process_tool_call(
                    auth=auth,
                    tc=tc,
                    messages=messages,
                    mcp_tool_names=mcp_tool_names,
                    citations=citations,
                    tool_calls_log=tool_calls_log,
                )
                for ev in tool_events:
                    yield ev

            # Loop back to the LLM with updated messages.

    async def _process_tool_call(  # noqa: C901
        self,
        auth: AsocAuthContext,
        tc: dict[str, str],
        messages: list[dict[str, Any]],
        mcp_tool_names: set[str],
        citations: list[dict[str, Any]],
        tool_calls_log: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Process a single tool call and append the tool-result message.

        Returns a list of SSE event dicts for the caller to yield.
        Modifies ``messages``, ``citations``, and ``tool_calls_log`` in place.
        """
        events: list[dict[str, str]] = []
        tool_id = tc["id"]
        tool_name = tc["name"]
        tool_args_str = tc["arguments"]

        if tool_name == "cite_source":
            try:
                parsed = json.loads(tool_args_str)
                citations.append(parsed)
                tool_calls_log.append({"tool": "cite_source", "args": parsed, "status": "done"})
            except json.JSONDecodeError:
                tool_calls_log.append(
                    {
                        "tool": "cite_source",
                        "args": tool_args_str,
                        "status": "error",
                        "reason": "invalid_json",
                    }
                )
            messages.append(
                {"role": "tool", "tool_call_id": tool_id, "content": json.dumps({"ok": True})}
            )
            return events

        if tool_name in mcp_tool_names:
            events.append(sse_tool_call(tool_name, "running"))
            content_str: str
            try:
                args: dict[str, Any] = json.loads(tool_args_str) if tool_args_str else {}
                result = await self._mcp_client.invoke(auth.session_id, tool_name, args)
                content_str = json.dumps({"content": result.content, "is_error": result.is_error})
                events.append(sse_tool_call(tool_name, "done"))
                tool_calls_log.append({"tool": tool_name, "args": args, "status": "done"})
            except ToolNotAllowedError:
                content_str = json.dumps({"error": "not_allowed"})
                events.append(sse_tool_call(tool_name, "error", reason="not_allowed"))
                tool_calls_log.append(
                    {"tool": tool_name, "status": "error", "reason": "not_allowed"}
                )
            except (McpUnavailableError, McpProtocolError, AsocMcpError) as exc:
                content_str = json.dumps({"error": str(exc)})
                events.append(sse_tool_call(tool_name, "error", reason="unavailable"))
                tool_calls_log.append(
                    {"tool": tool_name, "status": "error", "reason": "unavailable"}
                )
            messages.append({"role": "tool", "tool_call_id": tool_id, "content": content_str})
            return events

        # Unknown tool (hallucination) — return error so the LLM can recover.
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_id,
                "content": json.dumps({"error": "unknown_tool"}),
            }
        )
        return events
