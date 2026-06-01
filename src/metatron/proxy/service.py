"""ProxyService — single dispatch entrypoint for proxy + rag modes (MTRNIX-372)."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Callable, Literal
from uuid import uuid4

import structlog
from fastapi.responses import StreamingResponse

from metatron.core.events import PROXY_CALL_COMPLETED
from metatron.core.exceptions import MetatronError
from metatron.proxy.config import parse_upstream_config
from metatron.proxy.events import (
    PROXY_CONTEXT_ASSEMBLED,
    PROXY_ENRICHMENT_DEGRADED,
    PROXY_REQUEST_RECEIVED,
    PROXY_UPSTREAM_COMPLETED,
    PROXY_UPSTREAM_DISPATCHED,
    PROXY_UPSTREAM_ERROR,
    ProxyCallCompletedPayload,
)
from metatron.proxy.headers import enrichment_status, metronix_headers
from metatron.proxy.inject import inject_into_system

if TYPE_CHECKING:
    from metatron.agents.service import AgentRegistryService
    from metatron.core.config import Settings
    from metatron.core.events import EventBus
    from metatron.memory.assembler import AgentContextAssembler
    from metatron.memory.assembly_timeouts import AssemblyTimeouts
    from metatron.proxy.activity import ProxyActivityLogger
    from metatron.proxy.credentials import UpstreamCredentialsResolver
    from metatron.proxy.upstream import UpstreamLLMClient

logger = structlog.get_logger(__name__)


class AgentUpstreamNotConfiguredError(MetatronError):
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
            return obj["usage"]
    return None


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

    async def dispatch(
        self,
        *,
        agent_id: str | None,
        workspace_id: str,
        request_body: dict[str, Any],
        mode: Literal["proxy", "rag"],
    ) -> StreamingResponse:
        if mode == "proxy":
            return await self._dispatch_proxy(agent_id, workspace_id, request_body)
        return await self._dispatch_rag(agent_id, workspace_id, request_body)

    async def _dispatch_proxy(
        self, agent_id: str | None, workspace_id: str, request_body: dict[str, Any]
    ) -> StreamingResponse:
        from metatron.memory.assembly_timeouts import AssemblyTimeouts

        correlation_id = uuid4().hex
        activity = self._activity_factory(workspace_id)
        assert agent_id is not None  # route guarantees X-Agent-Id on proxy
        agent = await self._agents.get_agent(agent_id)
        upstream = parse_upstream_config(agent.current_config)
        if upstream is None:
            raise AgentUpstreamNotConfiguredError(
                "agent has no current_config.upstream"
            )

        messages = list(request_body.get("messages") or [])
        await activity.log(
            agent_id=agent_id, event_type=PROXY_REQUEST_RECEIVED,
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
            agent_id, workspace_id,
            messages=messages,
            correlation_id=correlation_id,
            capabilities=agent.capabilities,
            timeouts=timeouts,
        )
        await activity.log(
            agent_id=agent_id, event_type=PROXY_CONTEXT_ASSEMBLED,
            correlation_id=correlation_id,
            data={
                "preferences_n": context.preferences_count,
                "memories_n": context.memories_count,
                "knowledge_n": context.knowledge_count,
                **{f"{k}_ms": v for k, v in context.per_stage_ms.items()},
            },
        )
        for section in context.degraded_sections:
            await activity.log(
                agent_id=agent_id, event_type=PROXY_ENRICHMENT_DEGRADED,
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
            agent_id=agent_id, event_type=PROXY_UPSTREAM_DISPATCHED,
            correlation_id=correlation_id,
            data={
                "upstream_provider": upstream.provider,
                "upstream_model": upstream.model_name,
            },
        )

        _enrichment = enrichment_status(
            context.degraded_sections,
            requested=["memories"] + (
                ["knowledge"] if "knowledge_base" in agent.capabilities else []
            ),
        )
        headers = metronix_headers(
            correlation_id=correlation_id, agent_id=agent_id,
            enrichment=_enrichment, upstream_status=None,
        )

        async def _generate() -> Any:
            t0 = time.monotonic()
            usage: dict[str, Any] | None = None
            error_reason: str | None = None
            try:
                async for frame in self._upstream.stream(
                    upstream=upstream, api_key=api_key, messages=enriched,
                    request_body=request_body, correlation_id=correlation_id,
                ):
                    found = _usage_from_frame(frame.raw)
                    if found:
                        usage = found
                    yield frame.raw
            except asyncio.CancelledError:
                await activity.log(
                    agent_id=agent_id, event_type="proxy.client.cancelled",
                    correlation_id=correlation_id,
                    data={"bytes_streamed": 0, "ms_elapsed": int((time.monotonic() - t0) * 1000)},
                )
                raise
            except Exception as exc:  # noqa: BLE001 — surface as upstream error
                error_reason = str(exc)
                logger.warning("proxy.upstream_stream_error", error=error_reason)
            latency_ms = int((time.monotonic() - t0) * 1000)
            status = self._upstream.last_status or 0
            ok = error_reason is None and 200 <= status < 300
            await activity.log(
                agent_id=agent_id,
                event_type=PROXY_UPSTREAM_COMPLETED if ok else PROXY_UPSTREAM_ERROR,
                correlation_id=correlation_id,
                data={
                    "upstream_status": status, "latency_ms": latency_ms,
                    "prompt_tokens": (usage or {}).get("prompt_tokens"),
                    "completion_tokens": (usage or {}).get("completion_tokens"),
                    "reason": error_reason,
                },
            )
            payload = ProxyCallCompletedPayload(
                correlation_id=correlation_id, workspace_id=workspace_id,
                agent_id=agent_id,
                upstream_provider=upstream.provider, upstream_model=upstream.model_name,
                prompt_tokens=(usage or {}).get("prompt_tokens"),
                completion_tokens=(usage or {}).get("completion_tokens"),
                latency_ms=latency_ms, ttft_ms=None,
                finish_reason=None, upstream_status=status, error_reason=error_reason,
            )
            try:
                await self._bus.emit(PROXY_CALL_COMPLETED, asdict(payload))
            except Exception:  # noqa: BLE001
                logger.warning("proxy.bus_emit_failed")

        return StreamingResponse(
            _generate(), media_type="text/event-stream", headers=headers
        )

    async def _dispatch_rag(
        self, agent_id: str | None, workspace_id: str, request_body: dict[str, Any]
    ) -> StreamingResponse:
        raise NotImplementedError("rag mode added in Task 21")
