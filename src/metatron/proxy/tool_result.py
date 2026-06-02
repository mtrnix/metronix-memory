"""ToolResultEnricher — additive entity-driven enrichment (MTRNIX-372)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable  # noqa: TC003
from typing import TYPE_CHECKING, Any

import structlog

from metatron.memory.assembler import AgentContextAssembler
from metatron.proxy.events import (
    PROXY_TOOL_RESULT_ENRICHMENT_APPLIED,
    PROXY_TOOL_RESULT_ENRICHMENT_SKIPPED,
)

if TYPE_CHECKING:
    from metatron.core.config import Settings
    from metatron.core.models import AssembledContext
    from metatron.proxy.activity import ProxyActivityLogger
    from metatron.proxy.entity_trie import WorkspaceEntityTrie

logger = structlog.get_logger(__name__)

_MAX_ENTITIES = 5
_PER_ENTITY_LIMIT = 3

FetchMemories = Callable[[str, str, str], Awaitable[list[dict[str, Any]]]]


class ToolResultEnricher:
    def __init__(
        self,
        *,
        trie: WorkspaceEntityTrie,
        fetch_memories: FetchMemories,
        settings: Settings,
        activity_logger: ProxyActivityLogger,
    ) -> None:
        self._trie = trie
        self._fetch = fetch_memories
        self._settings = settings
        self._activity = activity_logger

    async def enrich(
        self,
        *,
        context: AssembledContext,
        tool_result_text: str,
        agent_id: str,
        workspace_id: str,
        correlation_id: str,
    ) -> None:
        t0 = time.monotonic()
        timeout_s = self._settings.proxy_tool_result_enrichment_timeout_ms / 1000
        try:
            await asyncio.wait_for(
                self._enrich_inner(
                    context, tool_result_text, agent_id, workspace_id, correlation_id, t0
                ),
                timeout=timeout_s,
            )
        except TimeoutError:
            await self._skip(agent_id, correlation_id, "timeout", t0)
        except Exception as exc:  # noqa: BLE001 — fail open
            logger.warning("tool_result_enrich.error", error=str(exc))
            await self._skip(agent_id, correlation_id, "error", t0)

    async def _enrich_inner(
        self,
        context: AssembledContext,
        tool_result_text: str,
        agent_id: str,
        workspace_id: str,
        correlation_id: str,
        t0: float,
    ) -> None:
        matched = await self._trie.match(tool_result_text, workspace_id)
        if not matched:
            await self._skip(agent_id, correlation_id, "no_entity_match", t0)
            return

        existing = context.sections.get("relevant_memories", "")
        new_lines: list[str] = []
        for entity in matched[:_MAX_ENTITIES]:
            rows = await self._fetch(workspace_id, entity, agent_id)
            for row in rows[:_PER_ENTITY_LIMIT]:
                content = str(row.get("content") or "")
                if content and content not in existing and content not in "\n".join(new_lines):
                    new_lines.append(f"- {content}")

        if not new_lines:
            await self._skip(agent_id, correlation_id, "no_entity_match", t0)
            return

        appended = "\n".join(new_lines)
        context.sections["relevant_memories"] = (
            f"{existing}\n{appended}" if existing else appended
        )
        # Rebuild the system prompt from updated sections
        context.system_prompt = AgentContextAssembler._render(context.sections)
        context.memories_count += len(new_lines)

        await self._activity.log(
            agent_id=agent_id,
            event_type=PROXY_TOOL_RESULT_ENRICHMENT_APPLIED,
            correlation_id=correlation_id,
            data={
                "entities_matched_n": len(matched),
                "memories_appended_n": len(new_lines),
                "tokens_appended": len(appended) // 4,
                "ms": int((time.monotonic() - t0) * 1000),
            },
        )

    async def _skip(
        self, agent_id: str, correlation_id: str, reason: str, t0: float
    ) -> None:
        await self._activity.log(
            agent_id=agent_id,
            event_type=PROXY_TOOL_RESULT_ENRICHMENT_SKIPPED,
            correlation_id=correlation_id,
            data={"reason": reason, "ms": int((time.monotonic() - t0) * 1000)},
        )
