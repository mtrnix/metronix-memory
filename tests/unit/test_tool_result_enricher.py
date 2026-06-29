"""ToolResultEnricher (PROJ-372 P4)."""

from unittest.mock import AsyncMock, MagicMock

from metronix.core.config import Settings
from metronix.core.models import AssembledContext
from metronix.memory.assembler import AgentContextAssembler
from metronix.proxy.tool_result import ToolResultEnricher


def _ctx() -> AssembledContext:
    sections = {
        "constitution": "",
        "preferences": "- pref",
        "relevant_memories": "- [0.9] existing fact",
        "relevant_knowledge": "- kb",
    }
    return AssembledContext(
        system_prompt=AgentContextAssembler._render(sections),
        sections=sections,
        memories_count=1,
    )


def _enricher(trie_matches: list[str], mem_rows: list[dict]) -> ToolResultEnricher:
    trie = MagicMock()
    trie.match = AsyncMock(return_value=trie_matches)
    fetch = AsyncMock(return_value=mem_rows)
    return ToolResultEnricher(
        trie=trie,
        fetch_memories=fetch,
        settings=Settings(),
        activity_logger=AsyncMock(),
    )


async def test_no_entity_match_skips() -> None:
    ctx = _ctx()
    before = ctx.sections["relevant_memories"]
    enr = _enricher([], [])
    await enr.enrich(
        context=ctx,
        tool_result_text="nothing",
        agent_id="A",
        workspace_id="WS",
        correlation_id="c",
    )
    assert ctx.sections["relevant_memories"] == before


async def test_match_appends_additively() -> None:
    ctx = _ctx()
    prefs_before = ctx.sections["preferences"]
    know_before = ctx.sections["relevant_knowledge"]
    enr = _enricher(["Acme"], [{"id": "m1", "content": "Acme is a client"}])
    await enr.enrich(
        context=ctx,
        tool_result_text="Acme shipped",
        agent_id="A",
        workspace_id="WS",
        correlation_id="c",
    )
    assert "Acme is a client" in ctx.sections["relevant_memories"]
    assert "existing fact" in ctx.sections["relevant_memories"]  # not rebuilt away
    # additive invariant: other sections untouched
    assert ctx.sections["preferences"] == prefs_before
    assert ctx.sections["relevant_knowledge"] == know_before
    # system_prompt rebuilt with the appended memory
    assert "Acme is a client" in ctx.system_prompt


async def test_dedup_existing_memory() -> None:
    ctx = _ctx()
    enr = _enricher(["Acme"], [{"id": "m1", "content": "existing fact"}])
    await enr.enrich(
        context=ctx,
        tool_result_text="Acme",
        agent_id="A",
        workspace_id="WS",
        correlation_id="c",
    )
    # "existing fact" already present -> not duplicated
    assert ctx.sections["relevant_memories"].count("existing fact") == 1
