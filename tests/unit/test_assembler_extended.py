"""Extended assembler (PROJ-372 P2)."""

from unittest.mock import AsyncMock

from metronix.core.config import Settings
from metronix.core.models import MemoryRecord, MemorySearchResult
from metronix.memory.assembler import AgentContextAssembler


def _record(content: str) -> MemoryRecord:
    return MemoryRecord(workspace_id="WS", agent_id="A", content=content)


def _make_assembler(*, prefs=None, mems=None, knowledge=None) -> AgentContextAssembler:
    mem_service = AsyncMock()
    mem_service.list_preferences.return_value = prefs or []
    mem_search = AsyncMock()
    mem_search.hybrid_search.return_value = mems or []
    settings = Settings()
    asm = AgentContextAssembler(
        memory_service=mem_service, memory_search=mem_search, settings=settings
    )
    # inject a knowledge retriever stub (added in this task)
    asm._knowledge_fetch = AsyncMock(return_value=knowledge or [])  # type: ignore[attr-defined]
    return asm


async def test_back_compat_user_message_path() -> None:
    asm = _make_assembler(prefs=[_record("likes brevity")])
    ctx = await asm.assemble("A", "WS", user_message="hello")
    assert "<preferences>" in ctx.system_prompt
    assert ctx.preferences_count == 1
    assert "preferences" in ctx.sections


async def test_messages_path_with_knowledge_capability() -> None:
    asm = _make_assembler(
        mems=[MemorySearchResult(record=_record("fact one"), score=0.9)],
        knowledge=[{"title": "KB", "url": "http://k", "text": "kb body"}],
    )
    ctx = await asm.assemble(
        "A",
        "WS",
        messages=[{"role": "user", "content": "what is the status"}],
        capabilities=["knowledge_base"],
        correlation_id="corr-1",
    )
    assert "<relevant_memories>" in ctx.system_prompt
    assert "<relevant_knowledge>" in ctx.system_prompt
    assert ctx.knowledge_count == 1
    assert ctx.correlation_id == "corr-1"
    assert "memories" in ctx.per_stage_ms


async def test_knowledge_skipped_without_capability() -> None:
    asm = _make_assembler(knowledge=[{"title": "KB", "text": "x"}])
    ctx = await asm.assemble(
        "A",
        "WS",
        messages=[{"role": "user", "content": "hi there friend"}],
        capabilities=[],
    )
    assert "<relevant_knowledge>" not in ctx.system_prompt
    assert ctx.knowledge_count == 0


async def test_degraded_section_recorded() -> None:
    asm = _make_assembler()
    asm._memory_search.hybrid_search.side_effect = RuntimeError("qdrant down")
    ctx = await asm.assemble(
        "A", "WS", messages=[{"role": "user", "content": "status please now"}]
    )
    assert "memories" in ctx.degraded_sections
    # assembly still succeeds
    assert isinstance(ctx.system_prompt, str)


async def test_requires_messages_or_user_message() -> None:
    asm = _make_assembler()
    try:
        await asm.assemble("A", "WS")
    except ValueError as exc:
        assert "messages" in str(exc)
    else:
        raise AssertionError("expected ValueError")
