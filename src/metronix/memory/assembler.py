"""AgentContextAssembler — structured system prompt for agent LLM calls.

Sections in strict order (XML-delimited): <constitution> (reserved-empty in
MTRNIX-372), <preferences>, <relevant_memories>, <relevant_knowledge>, and
the numeric-only <session_ledger> metadata section.
Empty sections are omitted from system_prompt but kept in `sections` (as "")
so tool-result enrichment can append additively (MTRNIX-372). D-020.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import structlog

from metronix.core.models import AssembledContext, MemoryKind
from metronix.memory.assembly_timeouts import AssemblyTimeouts
from metronix.memory.knowledge_section import format_knowledge_fragments
from metronix.memory.query_rewrite import QueryRewriter

if TYPE_CHECKING:
    from metronix.core.config import Settings
    from metronix.memory.search import MemorySearchService
    from metronix.memory.service import MemoryService
    from metronix.storage.conversation_postgres import ConversationPostgresStore

logger = structlog.get_logger(__name__)

_KNOWLEDGE_CAPABILITY = "knowledge_base"
_SECTION_ORDER = [
    "constitution",
    "preferences",
    "relevant_memories",
    "relevant_knowledge",
    "session_ledger",
]


class AgentContextAssembler:
    """Assembles structured system prompt for agent LLM calls.

    Usage::

        assembler = AgentContextAssembler(
            memory_service=svc,
            memory_search=search_svc,
            settings=settings,
        )
        ctx = await assembler.assemble(
            agent_id="agent-1",
            workspace_id="WS1",
            user_message="What did we discuss?",
        )
        # ctx.system_prompt contains XML-delimited sections
    """

    def __init__(
        self,
        memory_service: MemoryService,
        memory_search: MemorySearchService | None,
        settings: Settings,
        *,
        conversation_events: ConversationPostgresStore | None = None,
    ) -> None:
        self._memory_service = memory_service
        self._memory_search = memory_search
        self._settings = settings
        self._rewriter = QueryRewriter(settings=settings)
        self._conversation_events = conversation_events

    async def assemble(
        self,
        agent_id: str,
        workspace_id: str,
        user_message: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
        correlation_id: str | None = None,
        capabilities: list[str] | None = None,
        timeouts: AssemblyTimeouts | None = None,
        memory_top_k: int | None = None,
        session_id: str | None = None,
    ) -> AssembledContext:
        """Assemble the full system prompt with memory context.

        Either ``user_message`` (legacy back-compat) or ``messages`` (proxy path)
        must be provided.
        """
        if messages is None and user_message is None:
            msg = "assemble() requires either messages or user_message"
            raise ValueError(msg)
        if messages is None:
            messages = [{"role": "user", "content": user_message or ""}]
        correlation_id = correlation_id or uuid4().hex
        capabilities = capabilities or []
        timeouts = timeouts or AssemblyTimeouts.from_settings(self._settings)
        top_k = memory_top_k or self._settings.memory_injection_facts_top_k

        per_stage_ms: dict[str, int] = {}
        degraded: list[str] = []

        # 1. Query rewrite.
        t0 = time.monotonic()
        query, _used_slm, _fallback = await self._rewriter.rewrite(
            messages, timeout_s=timeouts.query_rewrite_s
        )
        per_stage_ms["query_rewrite"] = int((time.monotonic() - t0) * 1000)

        # 2. Parallel fan-out.
        prefs_text, prefs_n = await self._safe_section(
            "preferences",
            degraded,
            self._build_preferences_section(agent_id, workspace_id),
            timeout_s=None,
        )
        mem_t0 = time.monotonic()
        mem_text, mem_n = await self._safe_section(
            "memories",
            degraded,
            self._build_memories_section(agent_id, workspace_id, query, top_k),
            timeout_s=timeouts.memories_s,
        )
        per_stage_ms["memories"] = int((time.monotonic() - mem_t0) * 1000)

        know_text, know_n = "", 0
        if _KNOWLEDGE_CAPABILITY in capabilities:
            kn_t0 = time.monotonic()
            know_text, know_n = await self._safe_section(
                "knowledge",
                degraded,
                self._build_knowledge_section(workspace_id, query),
                timeout_s=timeouts.knowledge_s,
            )
            per_stage_ms["knowledge"] = int((time.monotonic() - kn_t0) * 1000)

        ledger_text, ledger_n = "", 0
        if session_id is not None and self._conversation_events is not None:
            ledger_text, ledger_n = await self._safe_section(
                "session_ledger",
                degraded,
                self._build_session_ledger_section(agent_id, workspace_id, session_id),
                timeout_s=None,
            )

        sections = {
            "constitution": "",  # reserved-empty (D10)
            "preferences": prefs_text,
            "relevant_memories": mem_text,
            "relevant_knowledge": know_text,
            "session_ledger": ledger_text,
        }
        system_prompt = self._render(sections)

        logger.info(
            "assembler.complete",
            agent_id=agent_id,
            workspace_id=workspace_id,
            correlation_id=correlation_id,
            preferences_count=prefs_n,
            memories_count=mem_n,
            knowledge_count=know_n,
            session_ledger_count=ledger_n,
            degraded=degraded,
        )
        return AssembledContext(
            system_prompt=system_prompt,
            preferences_count=prefs_n,
            memories_count=mem_n,
            knowledge_count=know_n,
            tokens_budget={
                "preferences": len(prefs_text) // 4,
                "memories": len(mem_text) // 4,
                "knowledge": len(know_text) // 4,
                "session_ledger": len(ledger_text) // 4,
            },
            sections=sections,
            degraded_sections=degraded,
            per_stage_ms=per_stage_ms,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    async def _safe_section(
        self,
        name: str,
        degraded: list[str],
        coro: Awaitable[tuple[str, int]],
        *,
        timeout_s: float | None,
    ) -> tuple[str, int]:
        try:
            if timeout_s is not None:
                return await asyncio.wait_for(coro, timeout=timeout_s)
            return await coro
        except Exception as exc:  # noqa: BLE001 — fail open, mark degraded
            logger.warning("assembler.section_degraded", section=name, error=str(exc))
            degraded.append(name)
            return "", 0

    async def _build_preferences_section(
        self, agent_id: str, workspace_id: str
    ) -> tuple[str, int]:
        records = await self._memory_service.list_preferences(workspace_id, agent_id)
        if not records:
            return "", 0
        return "\n".join(f"- {r.content}" for r in records), len(records)

    async def _build_memories_section(
        self, agent_id: str, workspace_id: str, query: str, top_k: int
    ) -> tuple[str, int]:
        if self._memory_search is None:
            return "", 0
        results = await self._memory_search.hybrid_search(
            workspace_id=workspace_id,
            query=query,
            agent_id=agent_id,
            kind_filter=[MemoryKind.FACT],
            top_k=top_k,
        )
        if not results:
            return "", 0
        return (
            "\n".join(f"- [{r.score:.2f}] {r.record.content}" for r in results),
            len(results),
        )

    async def _build_knowledge_section(self, workspace_id: str, query: str) -> tuple[str, int]:
        frags = await self._knowledge_fetch(workspace_id, query)
        return format_knowledge_fragments(frags)

    async def _build_session_ledger_section(
        self, agent_id: str, workspace_id: str, session_id: str
    ) -> tuple[str, int]:
        """Render only fixed numeric ledger metadata, never source event content.

        Ledgers may eventually gain richer extracted fields. Context injection
        deliberately exposes only schema-owned counts so this boundary cannot
        replay raw temporary event text into an upstream prompt.
        """
        if self._conversation_events is None:
            return "", 0
        ledger = await self._conversation_events.get_ledger(workspace_id, agent_id, session_id)
        if ledger is None:
            return "", 0

        summary = ledger.summary

        def _count(field: str) -> int:
            value = summary.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
            return 0

        return (
            "\n".join(
                (
                    f"generation: {ledger.generation}",
                    f"source_event_count: {_count('source_event_count')}",
                    f"candidate_count: {_count('candidate_count')}",
                    f"rejected_candidate_count: {_count('rejected_candidate_count')}",
                )
            ),
            1,
        )

    async def _knowledge_fetch(self, workspace_id: str, query: str) -> list[dict[str, Any]]:
        """Retrieval-only KB fetch (no LLM). Overridable in tests."""
        from metronix.retrieval.search import fast_search

        results = await fast_search(
            query, workspace_id=workspace_id, top_k=self._settings.proxy_knowledge_top_k
        )
        return cast(list[dict[str, Any]], results)

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _render(sections: dict[str, str]) -> str:
        """Combine sections with XML delimiters in strict order.

        Empty sections are omitted from the prompt but the key stays in
        ``sections`` dict (value "") so enrichment can append later.
        """
        parts: list[str] = []
        for name in _SECTION_ORDER:
            body = sections.get(name, "")
            if body:
                parts.append(f"<{name}>\n{body}\n</{name}>")
        return "\n\n".join(parts)

    # Keep backward-compatible alias for existing callers.
    @staticmethod
    def _assemble_system_prompt(
        constitution: str,
        preferences: str,
        memories: str,
    ) -> str:
        """Legacy alias — callers that construct sections manually."""
        return AgentContextAssembler._render(
            {
                "constitution": constitution,
                "preferences": preferences,
                "relevant_memories": memories,
            }
        )
