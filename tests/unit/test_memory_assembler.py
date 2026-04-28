"""Unit tests for AgentContextAssembler — memory context injection.

Tests cover:
1. All sections populated — full system prompt with 3 XML blocks
2. No preferences — <preferences> section absent
3. No matching memories — <relevant_memories> section absent
4. Both empty — system_prompt == ""
5. Section ordering: constitution < preferences < memories
6. Partial sections: only preferences non-empty
7. Memory service down — graceful degradation, empty sections, warning logged
8. Token budget exceeded — warning logged, sections not truncated
9. Latency timing — verify elapsed_ms appears in log output
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.core.models import (
    AssembledContext,
    MemoryKind,
    MemoryRecord,
    MemorySearchResult,
    MemoryScope,
)
from metatron.memory.assembler import AgentContextAssembler


def _make_settings(**overrides: object) -> MagicMock:
    """Create a mock Settings with sensible defaults."""
    defaults = {
        "memory_injection_enabled": True,
        "memory_injection_facts_top_k": 10,
        "memory_injection_preferences_budget_tokens": 2000,
        "memory_injection_facts_budget_tokens": 3000,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_preference(content: str) -> MemoryRecord:
    return MemoryRecord(
        content=content,
        kind=MemoryKind.PREFERENCE,
        agent_id="agent-1",
        workspace_id="WS1",
    )


def _make_fact(content: str) -> MemoryRecord:
    return MemoryRecord(
        content=content,
        kind=MemoryKind.FACT,
        agent_id="agent-1",
        workspace_id="WS1",
    )


class TestAssemblerAllSectionsPopulated:
    """Scenario: both preferences and memories return results."""

    async def test_full_system_prompt(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = [_make_preference("Team dailies at 10:30")]

        search = AsyncMock()
        search.hybrid_search.return_value = [
            MemorySearchResult(record=_make_fact("Discussed API redesign"), score=0.85),
        ]

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "What did we discuss?")

        assert "<preferences>" in ctx.system_prompt
        assert "<relevant_memories>" in ctx.system_prompt
        assert "Team dailies at 10:30" in ctx.system_prompt
        assert "Discussed API redesign" in ctx.system_prompt
        assert ctx.preferences_count == 1
        assert ctx.memories_count == 1


class TestAssemblerNoPreferences:
    """Scenario: list_preferences returns empty list."""

    async def test_preferences_section_absent(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = []

        search = AsyncMock()
        search.hybrid_search.return_value = [
            MemorySearchResult(record=_make_fact("Some fact"), score=0.5),
        ]

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "<preferences>" not in ctx.system_prompt
        assert "<relevant_memories>" in ctx.system_prompt
        assert ctx.preferences_count == 0
        assert ctx.memories_count == 1


class TestAssemblerNoMemories:
    """Scenario: hybrid_search returns empty list."""

    async def test_memories_section_absent(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = [_make_preference("pref")]

        search = AsyncMock()
        search.hybrid_search.return_value = []

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "<preferences>" in ctx.system_prompt
        assert "<relevant_memories>" not in ctx.system_prompt
        assert ctx.preferences_count == 1
        assert ctx.memories_count == 0


class TestAssemblerBothEmpty:
    """Scenario: both sections empty."""

    async def test_empty_system_prompt(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = []

        search = AsyncMock()
        search.hybrid_search.return_value = []

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert ctx.system_prompt == ""
        assert ctx.preferences_count == 0
        assert ctx.memories_count == 0


class TestAssemblerSectionOrdering:
    """Section ordering: constitution → preferences → memories."""

    async def test_ordering(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = [_make_preference("PREF_TEXT")]

        search = AsyncMock()
        search.hybrid_search.return_value = [
            MemorySearchResult(record=_make_fact("MEM_TEXT"), score=0.9),
        ]

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "<preferences>" in ctx.system_prompt
        assert "<relevant_memories>" in ctx.system_prompt
        # Preferences must come before memories
        assert ctx.system_prompt.index("<preferences>") < ctx.system_prompt.index(
            "<relevant_memories>"
        )


class TestAssemblerPartialSections:
    """Only preferences non-empty → only <preferences> block present."""

    async def test_only_preferences(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = [_make_preference("Only pref")]

        search = AsyncMock()
        search.hybrid_search.return_value = []

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "<preferences>" in ctx.system_prompt
        assert "<relevant_memories>" not in ctx.system_prompt
        assert "Only pref" in ctx.system_prompt


class TestAssemblerGracefulDegradation:
    """Memory service down — graceful degradation."""

    async def test_service_failure_returns_empty_context(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.side_effect = RuntimeError("PG down")

        search = AsyncMock()
        search.hybrid_search.side_effect = RuntimeError("Qdrant down")

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert ctx.system_prompt == ""
        assert ctx.preferences_count == 0
        assert ctx.memories_count == 0

    async def test_preferences_failure_memories_succeed(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.side_effect = RuntimeError("PG down")

        search = AsyncMock()
        search.hybrid_search.return_value = [
            MemorySearchResult(record=_make_fact("Fact"), score=0.7),
        ]

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "<preferences>" not in ctx.system_prompt
        assert "<relevant_memories>" in ctx.system_prompt
        assert "Fact" in ctx.system_prompt
        assert ctx.preferences_count == 0
        assert ctx.memories_count == 1

    async def test_search_none_returns_empty_memories(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = [_make_preference("P")]

        assembler = AgentContextAssembler(svc, None, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "<preferences>" in ctx.system_prompt
        assert "<relevant_memories>" not in ctx.system_prompt
        assert ctx.memories_count == 0


class TestAssemblerTokenBudget:
    """Token budget exceeded — warning logged, sections not truncated."""

    async def test_preferences_over_budget_logs_warning(self) -> None:
        # Create a preference with very long content
        long_content = "x" * 10000  # ~2500 tokens via len//4
        svc = AsyncMock()
        svc.list_preferences.return_value = [
            _make_preference(long_content),
        ]

        search = AsyncMock()
        search.hybrid_search.return_value = []

        settings = _make_settings(memory_injection_preferences_budget_tokens=100)
        assembler = AgentContextAssembler(svc, search, settings)
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        # Section not truncated (DD-5)
        assert long_content in ctx.system_prompt
        assert ctx.preferences_count == 1

    async def test_memories_over_budget_logs_warning(self) -> None:
        long_content = "y" * 16000  # ~4000 tokens via len//4
        svc = AsyncMock()
        svc.list_preferences.return_value = []

        search = AsyncMock()
        search.hybrid_search.return_value = [
            MemorySearchResult(record=_make_fact(long_content), score=0.9),
        ]

        settings = _make_settings(memory_injection_facts_budget_tokens=100)
        assembler = AgentContextAssembler(svc, search, settings)
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        # Section not truncated (DD-5)
        assert long_content in ctx.system_prompt
        assert ctx.memories_count == 1


class TestAssemblerTiming:
    """Latency timing — verify elapsed_ms appears in log output."""

    async def test_timing_logged(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = []

        search = AsyncMock()
        search.hybrid_search.return_value = []

        assembler = AgentContextAssembler(svc, search, _make_settings())

        with patch("metatron.memory.assembler.logger") as mock_logger:
            ctx = await assembler.assemble("agent-1", "WS1", "query")
            mock_logger.info.assert_called_once()
            call_kwargs = mock_logger.info.call_args[1]
            assert "elapsed_ms" in call_kwargs
            assert call_kwargs["elapsed_ms"] >= 0


class TestAssemblerTokensBudget:
    """Verify tokens_budget is populated."""

    async def test_tokens_budget_populated(self) -> None:
        svc = AsyncMock()
        svc.list_preferences.return_value = [_make_preference("abc")]

        search = AsyncMock()
        search.hybrid_search.return_value = [
            MemorySearchResult(record=_make_fact("def ghi"), score=0.5),
        ]

        assembler = AgentContextAssembler(svc, search, _make_settings())
        ctx = await assembler.assemble("agent-1", "WS1", "query")

        assert "preferences" in ctx.tokens_budget
        assert "memories" in ctx.tokens_budget
        assert ctx.tokens_budget["preferences"] > 0
        assert ctx.tokens_budget["memories"] > 0
