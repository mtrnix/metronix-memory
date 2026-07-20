"""ProxyService — single dispatch entrypoint for proxy + rag modes (MTRNIX-372)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

import structlog
from fastapi.responses import StreamingResponse

from metronix.core.events import PROXY_CALL_COMPLETED
from metronix.core.exceptions import MetronixError
from metronix.proxy.config import parse_upstream_config
from metronix.proxy.events import (
    PROXY_CONTEXT_ASSEMBLED,
    PROXY_ENRICHMENT_DEGRADED,
    PROXY_QUERY_REWRITTEN,
    PROXY_REQUEST_RECEIVED,
    PROXY_TOOL_CALL_OBSERVED,
    PROXY_UPSTREAM_COMPLETED,
    PROXY_UPSTREAM_DISPATCHED,
    PROXY_UPSTREAM_ERROR,
    ProxyCallCompletedPayload,
)
from metronix.proxy.headers import enrichment_status, metronix_headers
from metronix.proxy.inject import inject_into_system

if TYPE_CHECKING:
    from metronix.agents.service import AgentRegistryService
    from metronix.core.config import Settings
    from metronix.core.events import EventBus
    from metronix.memory.assembler import AgentContextAssembler
    from metronix.memory.assembly_timeouts import AssemblyTimeouts
    from metronix.memory.compaction import CompactionController
    from metronix.proxy.activity import ProxyActivityLogger
    from metronix.proxy.credentials import UpstreamCredentialsResolver
    from metronix.proxy.upstream import UpstreamLLMClient
    from metronix.storage.conversation_postgres import ConversationPostgresStore

logger = structlog.get_logger(__name__)
_CONVERSATION_SESSION_ID_PATTERN = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")


class AgentUpstreamNotConfiguredError(MetronixError):
    """The resolved agent has no current_config.upstream block."""


def _usage_from_frame(raw: bytes) -> dict[str, Any] | None:
    """Best-effort parse of an SSE 'data: {json}' frame carrying usage."""
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload in (b"", b"[DONE]"):
            continue
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("usage"):
            usage = obj["usage"]
            return usage if isinstance(usage, dict) else None
    return None


def _assistant_text_from_frame(raw: bytes) -> str:
    """Extract assistant delta text without changing the client-visible SSE bytes."""
    parts: list[str] = []
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload in (b"", b"[DONE]"):
            continue
        try:
            body = json.loads(payload)
        except (ValueError, TypeError):
            continue
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list):
            continue
        for choice in choices:
            delta = choice.get("delta") if isinstance(choice, dict) else None
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str):
                parts.append(content)
    return "".join(parts)


class _SseCompletionDetector:
    """Recognize a complete ``data: [DONE]`` SSE event across raw chunks."""

    def __init__(self) -> None:
        self._pending = b""
        self._event_data: list[bytes] = []
        self.completed = False

    def feed(self, raw: bytes) -> None:
        """Consume raw bytes without changing the byte stream sent to the client."""
        self._pending += raw
        while b"\n" in self._pending:
            line, self._pending = self._pending.split(b"\n", 1)
            if line.endswith(b"\r"):
                line = line[:-1]
            if not line:
                if b"\n".join(self._event_data) == b"[DONE]":
                    self.completed = True
                self._event_data.clear()
                continue
            if line.startswith(b":"):
                continue
            field, separator, value = line.partition(b":")
            if field == b"data" and separator:
                if value.startswith(b" "):
                    value = value[1:]
                self._event_data.append(value)


def _conversation_session_id(request_body: dict[str, Any]) -> str | None:
    """Read the optional opaque session id from the proxy request body."""
    value = request_body.get("conversation_id", request_body.get("session_id"))
    if not isinstance(value, str):
        return None
    value = value.strip()
    if _CONVERSATION_SESSION_ID_PATTERN.match(value) is None:
        return None
    return value


class ProxyService:
    def __init__(
        self,
        *,
        assembler: AgentContextAssembler,
        upstream_client: UpstreamLLMClient,
        credentials: UpstreamCredentialsResolver,
        agent_service: AgentRegistryService,
        event_bus: EventBus,
        settings: Settings,
        activity_logger_factory: Callable[[str], ProxyActivityLogger],
        timeouts: AssemblyTimeouts | None = None,
        tool_result_enricher_factory: Callable[[str], Any] | None = None,
        rag_stream_factory: Callable[..., Awaitable[StreamingResponse]] | None = None,
        conversation_events: ConversationPostgresStore | None = None,
        compaction: CompactionController | None = None,
    ) -> None:
        self._assembler = assembler
        self._upstream = upstream_client
        self._credentials = credentials
        self._agents = agent_service
        self._bus = event_bus
        self._settings = settings
        self._activity_factory = activity_logger_factory
        self._timeouts = timeouts
        self._enricher_factory = tool_result_enricher_factory
        # Injected from the L6 wiring (create_app) to avoid a proxy(L3)->api(L6)
        # upward import / circular dependency (MTRNIX-372 review BLOCKER 2).
        self._rag_stream_factory = rag_stream_factory
        self._conversation_events = conversation_events
        self._compaction = compaction

    async def dispatch(
        self,
        *,
        agent_id: str | None,
        workspace_id: str,
        request_body: dict[str, Any],
        mode: Literal["proxy", "rag"],
        user_id: str | None = None,
        plugin_manager: object | None = None,
    ) -> StreamingResponse:
        if mode == "proxy":
            return await self._dispatch_proxy(agent_id, workspace_id, request_body)
        return await self._dispatch_rag(
            workspace_id, request_body, user_id=user_id, plugin_manager=plugin_manager
        )

    async def _dispatch_proxy(
        self, agent_id: str | None, workspace_id: str, request_body: dict[str, Any]
    ) -> StreamingResponse:
        from metronix.memory.assembly_timeouts import AssemblyTimeouts

        correlation_id = uuid4().hex
        activity = self._activity_factory(workspace_id)
        if agent_id is None:  # route guarantees X-Agent-Id; explicit (survives -O)
            raise AgentUpstreamNotConfiguredError("agent_id required for proxy mode")
        agent = await self._agents.get_agent(agent_id)
        upstream = parse_upstream_config(agent.current_config)
        if upstream is None:
            raise AgentUpstreamNotConfiguredError("agent has no current_config.upstream")

        messages = list(request_body.get("messages") or [])
        session_id = _conversation_session_id(request_body)
        await activity.log(
            agent_id=agent_id,
            event_type=PROXY_REQUEST_RECEIVED,
            correlation_id=correlation_id,
            data={
                "model_requested": request_body.get("model"),
                "stream": bool(request_body.get("stream")),
                "msg_count": len(messages),
                "route": "proxy",
            },
        )

        timeouts = self._timeouts or AssemblyTimeouts.from_settings(self._settings)
        context = await self._assembler.assemble(
            agent_id,
            workspace_id,
            messages=messages,
            correlation_id=correlation_id,
            capabilities=agent.capabilities,
            timeouts=timeouts,
            session_id=session_id,
        )
        await activity.log(
            agent_id=agent_id,
            event_type=PROXY_CONTEXT_ASSEMBLED,
            correlation_id=correlation_id,
            data={
                "preferences_n": context.preferences_count,
                "memories_n": context.memories_count,
                "knowledge_n": context.knowledge_count,
                **{f"{k}_ms": v for k, v in context.per_stage_ms.items()},
            },
        )
        await activity.log(
            agent_id=agent_id,
            event_type=PROXY_QUERY_REWRITTEN,
            correlation_id=correlation_id,
            data={"rewrite_ms": context.per_stage_ms.get("query_rewrite", 0)},
        )
        for section in context.degraded_sections:
            await activity.log(
                agent_id=agent_id,
                event_type=PROXY_ENRICHMENT_DEGRADED,
                correlation_id=correlation_id,
                data={"stage": section, "reason": "timeout_or_error"},
            )

        # Tool-result enrichment (P4 — enricher may be None in P3).
        is_tool_round = bool(messages) and messages[-1].get("role") == "tool"
        if (
            is_tool_round
            and self._settings.proxy_tool_result_enrichment
            and self._enricher_factory is not None
        ):
            enricher = self._enricher_factory(workspace_id)
            await enricher.enrich(
                context=context,
                tool_result_text=str(messages[-1].get("content") or ""),
                agent_id=agent_id,
                workspace_id=workspace_id,
                correlation_id=correlation_id,
            )

        enriched = inject_into_system(messages, context.system_prompt)
        api_key = await self._credentials.resolve(upstream.api_key_ref, workspace_id)

        await activity.log(
            agent_id=agent_id,
            event_type=PROXY_UPSTREAM_DISPATCHED,
            correlation_id=correlation_id,
            data={
                "upstream_provider": upstream.provider,
                "upstream_model": upstream.model_name,
            },
        )

        _enrichment = enrichment_status(
            context.degraded_sections,
            requested=["memories"]
            + (["knowledge"] if "knowledge_base" in agent.capabilities else []),
        )
        headers = metronix_headers(
            correlation_id=correlation_id,
            agent_id=agent_id,
            enrichment=_enrichment,
            upstream_status=None,
        )

        async def _generate() -> Any:
            t0 = time.monotonic()
            usage: dict[str, Any] | None = None
            assistant_text: list[str] = []
            error_reason: str | None = None
            status = 0  # per-call, captured from frames (no shared-state race)
            completion = _SseCompletionDetector()
            try:
                async for frame in self._upstream.stream(
                    upstream=upstream,
                    api_key=api_key,
                    messages=enriched,
                    request_body=request_body,
                    correlation_id=correlation_id,
                ):
                    if frame.status is not None:
                        status = frame.status
                    found = _usage_from_frame(frame.raw)
                    if found:
                        usage = found
                    assistant_text.append(_assistant_text_from_frame(frame.raw))
                    if b'"tool_calls"' in frame.raw:
                        await activity.log(
                            agent_id=agent_id,
                            event_type=PROXY_TOOL_CALL_OBSERVED,
                            correlation_id=correlation_id,
                            data={"arguments_bytes": min(len(frame.raw), 8192)},
                        )
                    yield frame.raw
                    completion.feed(frame.raw)
            except asyncio.CancelledError:
                await activity.log(
                    agent_id=agent_id,
                    event_type="proxy.client.cancelled",
                    correlation_id=correlation_id,
                    data={"bytes_streamed": 0, "ms_elapsed": int((time.monotonic() - t0) * 1000)},
                )
                raise
            except Exception as exc:  # noqa: BLE001 — surface as upstream error
                error_reason = str(exc)
                logger.warning("proxy.upstream_stream_error", error=error_reason)
                # Terminal error frame so the client can detect a mid-stream
                # failure (status 200 + headers were already sent). W5.
                yield (
                    b'data: {"error": {"message": "upstream stream error", '
                    b'"type": "upstream_error"}}\n\n'
                )
                yield b"data: [DONE]\n\n"
            latency_ms = int((time.monotonic() - t0) * 1000)
            ok = error_reason is None and 200 <= status < 300 and completion.completed
            if ok and session_id is not None and self._conversation_events is not None:
                asyncio.create_task(
                    self._capture_completed_conversation(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        session_id=session_id,
                        request_messages=messages,
                        assistant_text="".join(assistant_text),
                        activity=activity,
                        correlation_id=correlation_id,
                    ),
                    name="proxy-conversation-capture",
                )
            await activity.log(
                agent_id=agent_id,
                event_type=PROXY_UPSTREAM_COMPLETED if ok else PROXY_UPSTREAM_ERROR,
                correlation_id=correlation_id,
                data={
                    "upstream_status": status,
                    "latency_ms": latency_ms,
                    "prompt_tokens": (usage or {}).get("prompt_tokens"),
                    "completion_tokens": (usage or {}).get("completion_tokens"),
                    "reason": error_reason,
                },
            )
            payload = ProxyCallCompletedPayload(
                correlation_id=correlation_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                upstream_provider=upstream.provider,
                upstream_model=upstream.model_name,
                prompt_tokens=(usage or {}).get("prompt_tokens"),
                completion_tokens=(usage or {}).get("completion_tokens"),
                latency_ms=latency_ms,
                ttft_ms=None,
                finish_reason=None,
                upstream_status=status,
                error_reason=error_reason,
            )
            try:
                await self._bus.emit(PROXY_CALL_COMPLETED, asdict(payload))
            except Exception:  # noqa: BLE001
                logger.warning("proxy.bus_emit_failed")

        return StreamingResponse(_generate(), media_type="text/event-stream", headers=headers)

    async def _capture_completed_conversation(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        request_messages: list[dict[str, Any]],
        assistant_text: str,
        activity: ProxyActivityLogger,
        correlation_id: str,
    ) -> None:
        """Persist a completed exchange in the background without logging content."""
        from metronix.memory.conversation_models import ConversationEvent

        events_store = self._conversation_events
        if events_store is None:
            return
        events: list[ConversationEvent] = []
        for message in request_messages:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                events.append(
                    ConversationEvent.new(workspace_id, agent_id, session_id, role, content)
                )
        if assistant_text:
            events.append(
                ConversationEvent.new(
                    workspace_id,
                    agent_id,
                    session_id,
                    "assistant",
                    assistant_text,
                )
            )

        try:
            for event in events:
                await events_store.append_event(event)

            # Task 1 exposes no durable atomic claim/acknowledgement operation.
            # Do not invoke automatic compaction here, even when its feature
            # flag is enabled: separate read and write operations can let
            # concurrent API processes compact the same rows. Explicit,
            # authenticated compaction remains available through its route.
            compacted = False

            await activity.log(
                agent_id=agent_id,
                event_type="conversation.events.captured",
                correlation_id=correlation_id,
                session_id=session_id,
                data={"event_count": len(events), "automatic_compacted": compacted},
            )
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort after SSE completion
            logger.warning(
                "proxy.conversation_capture_failed",
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                error_type=type(exc).__name__,
            )

    async def _dispatch_rag(
        self,
        workspace_id: str,
        request_body: dict[str, Any],
        *,
        user_id: str | None = None,
        plugin_manager: object | None = None,
    ) -> StreamingResponse:
        """Legacy RAG mode: Metronix answers via hybrid_search_and_answer.

        Delegates to the injected ``rag_stream_factory`` (wired in create_app to
        openai_compat.build_rag_stream) so SSE output is byte-identical to the
        pre-refactor handler, WITHOUT a proxy(L3)->api(L6) import. ``user_id``
        and ``plugin_manager`` are threaded through to preserve telemetry
        attribution and plugin pipeline hooks (MTRNIX-372 A-full).
        """
        if self._rag_stream_factory is None:
            raise RuntimeError("rag_stream_factory not configured for rag mode")
        return await self._rag_stream_factory(
            request_body=request_body,
            workspace_id=workspace_id,
            user_id=user_id or "openai-default",
            plugin_manager=plugin_manager,
        )
