"""AgentContextAssembler — assembles structured system prompt for agent LLM calls.

Three XML-delimited sections in strict order:
1. ``<constitution>`` — from agent config (reserved, empty in v1)
2. ``<preferences>`` — all active preference+pinned records (always-on, no retrieval)
3. ``<relevant_memories>`` — top-K fact records via hybrid search

No ``<relevant_knowledge>`` section in v1 (DD-4).
Design: D-020 in ``docs/adr/2026-04-25-metatron-strategy.md`` §4.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import AssembledContext, MemoryKind

if TYPE_CHECKING:
    from metatron.core.config import Settings
    from metatron.memory.search import MemorySearchService
    from metatron.memory.service import MemoryService

logger = structlog.get_logger(__name__)


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
    ) -> None:
        self._memory_service = memory_service
        self._memory_search = memory_search
        self._settings = settings

    async def assemble(
        self,
        agent_id: str,
        workspace_id: str,
        user_message: str,
        *,
        memory_top_k: int | None = None,
    ) -> AssembledContext:
        """Assemble the full system prompt with memory context.

        Each section is built independently with graceful degradation:
        a failing section becomes empty and other sections proceed.
        """
        t0 = time.monotonic()

        top_k = memory_top_k or self._settings.memory_injection_facts_top_k

        # Build sections with graceful degradation.
        constitution_text = ""  # Reserved for v1 (DD-4).
        preferences_text, preferences_count = await self._build_preferences_section(
            agent_id, workspace_id,
        )
        memories_text, memories_count = await self._build_memories_section(
            agent_id, workspace_id, user_message, top_k,
        )

        system_prompt = self._assemble_system_prompt(
            constitution_text, preferences_text, memories_text,
        )

        # Approximate token budget tracking (DD-6). Warning-only (DD-5).
        est_pref_tokens = (len(preferences_text) // 4) if preferences_text else 0
        est_mem_tokens = (len(memories_text) // 4) if memories_text else 0

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "assembler.complete",
            agent_id=agent_id,
            workspace_id=workspace_id,
            elapsed_ms=round(elapsed_ms, 1),
            preferences_count=preferences_count,
            memories_count=memories_count,
            est_pref_tokens=est_pref_tokens,
            est_mem_tokens=est_mem_tokens,
        )

        return AssembledContext(
            system_prompt=system_prompt,
            preferences_count=preferences_count,
            memories_count=memories_count,
            tokens_budget={"preferences": est_pref_tokens, "memories": est_mem_tokens},
        )

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    async def _build_preferences_section(
        self,
        agent_id: str,
        workspace_id: str,
    ) -> tuple[str, int]:
        """Fetch ALL active preference+pinned records. No retrieval, no scoring."""
        try:
            records = await self._memory_service.list_preferences(workspace_id, agent_id)
        except Exception:
            logger.warning(
                "assembler.preferences_failed",
                agent_id=agent_id,
                workspace_id=workspace_id,
                exc_info=True,
            )
            return "", 0

        if not records:
            return "", 0

        lines = [f"- {r.content}" for r in records]
        text = "\n".join(lines)

        # Approximate token estimate (DD-6). Warning-only (DD-5).
        est_tokens = len(text) // 4
        if est_tokens > self._settings.memory_injection_preferences_budget_tokens:
            logger.warning(
                "assembler.preferences_over_budget",
                agent_id=agent_id,
                estimated_tokens=est_tokens,
                budget=self._settings.memory_injection_preferences_budget_tokens,
                note="estimate is approximate (DD-6), refine post-pilot",
            )
        return text, len(records)

    async def _build_memories_section(
        self,
        agent_id: str,
        workspace_id: str,
        query: str,
        top_k: int,
    ) -> tuple[str, int]:
        """Retrieve top-K fact records relevant to the query."""
        if self._memory_search is None:
            return "", 0

        try:
            results = await self._memory_search.hybrid_search(
                workspace_id=workspace_id,
                query=query,
                agent_id=agent_id,
                kind_filter=[MemoryKind.FACT],
                top_k=top_k,
            )
        except Exception:
            logger.warning(
                "assembler.memories_failed",
                agent_id=agent_id,
                workspace_id=workspace_id,
                exc_info=True,
            )
            return "", 0

        if not results:
            return "", 0

        lines = [f"- [{r.score:.2f}] {r.record.content}" for r in results]
        text = "\n".join(lines)

        # Approximate token estimate (DD-6). Warning-only (DD-5).
        est_tokens = len(text) // 4
        if est_tokens > self._settings.memory_injection_facts_budget_tokens:
            logger.warning(
                "assembler.memories_over_budget",
                agent_id=agent_id,
                estimated_tokens=est_tokens,
                budget=self._settings.memory_injection_facts_budget_tokens,
            )
        return text, len(results)

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _assemble_system_prompt(
        constitution: str,
        preferences: str,
        memories: str,
    ) -> str:
        """Combine sections with XML delimiters in strict order.

        Ordering: constitution → preferences → memories.
        Empty sections are omitted entirely.
        """
        sections: list[str] = []
        if constitution:
            sections.append(f"<constitution>\n{constitution}\n</constitution>")
        if preferences:
            sections.append(f"<preferences>\n{preferences}\n</preferences>")
        if memories:
            sections.append(f"<relevant_memories>\n{memories}\n</relevant_memories>")
        return "\n\n".join(sections)
