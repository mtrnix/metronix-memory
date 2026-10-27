"""Proxy session_id reaches the Redis session leg (issue #429).

Regression coverage for the wire-through fix:
- ``AgentContextAssembler.assemble(session_id=...)`` forwards the id to
  ``MemorySearchService.hybrid_search`` (proxied requests used to lose it).
- ``hybrid_search`` consults Redis only when a session id is present.
- The session leg matches records by substring of the retrieval query;
  non-matching records never enter the results.
- A failing Redis leg fails open instead of breaking retrieval.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metronix.core.config import Settings
from metronix.core.models import MemoryRecord
from metronix.memory.assembler import AgentContextAssembler
from metronix.memory.search import MemorySearchService


def _record(record_id: str, content: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="ws1",
        agent_id="agent1",
        content=content,
    )


def _make_assembler() -> tuple[AgentContextAssembler, AsyncMock]:
    mem_service = AsyncMock()
    mem_service.list_preferences.return_value = []
    mem_search = AsyncMock()
    mem_search.hybrid_search.return_value = []
    settings = Settings()
    asm = AgentContextAssembler(
        memory_service=mem_service, memory_search=mem_search, settings=settings
    )
    return asm, mem_search


async def test_assemble_forwards_session_id_to_hybrid_search() -> None:
    asm, mem_search = _make_assembler()
    await asm.assemble(
        "agent1",
        "ws1",
        messages=[{"role": "user", "content": "what did we discuss"}],
        session_id="sess-9",
    )
    call = mem_search.hybrid_search.await_args
    assert call is not None
    assert call.kwargs["session_id"] == "sess-9"


async def test_assemble_without_session_id_passes_none() -> None:
    asm, mem_search = _make_assembler()
    await asm.assemble(
        "agent1",
        "ws1",
        messages=[{"role": "user", "content": "what did we discuss"}],
    )
    call = mem_search.hybrid_search.await_args
    assert call is not None
    assert call.kwargs["session_id"] is None


def _make_search_service(*, redis=None) -> tuple[MemorySearchService, MagicMock]:
    qdrant = MagicMock()
    qdrant.search = AsyncMock(return_value=[])
    service = MemorySearchService(qdrant=qdrant, redis=redis)
    return service, qdrant


async def test_session_leg_runs_only_with_a_session_id() -> None:
    redis = MagicMock()
    redis.list = AsyncMock(return_value=[])
    service, _ = _make_search_service(redis=redis)

    await service.hybrid_search("ws1", "status update", session_id="sess-9")
    redis.list.assert_awaited_once_with("ws1", "sess-9")

    redis.list.reset_mock()
    await service.hybrid_search("ws1", "status update")
    redis.list.assert_not_awaited()


async def test_session_leg_matches_records_by_query_substring() -> None:
    matching = _record("r-match", "the deployment status update failed")
    non_matching = _record("r-other", "lunch menu for friday")
    redis = MagicMock()
    redis.list = AsyncMock(return_value=[matching, non_matching])
    service, _ = _make_search_service(redis=redis)

    results = await service.hybrid_search("ws1", "status update", session_id="sess-9")

    ids = [r.record.id for r in results]
    assert "r-match" in ids
    assert "r-other" not in ids


async def test_session_leg_fails_open() -> None:
    redis = MagicMock()
    redis.list = AsyncMock(side_effect=RuntimeError("redis down"))
    service, qdrant = _make_search_service(redis=redis)

    results = await service.hybrid_search("ws1", "status update", session_id="sess-9")

    assert isinstance(results, list)  # retrieval survives the leg failure
    qdrant.search.assert_awaited()


async def test_assembler_excludes_other_agents_and_nonfact_session_records() -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from metronix.core.models import MemoryKind

    own = _record("own", "status update for this agent")
    foreign = replace(own, id="foreign", agent_id="agent2", content="status update secret")
    preference = replace(own, id="pref", kind=MemoryKind.PREFERENCE)
    pinned = replace(own, id="pin", kind=MemoryKind.PINNED)
    redis = MagicMock()
    redis.list = AsyncMock(return_value=[own, foreign, preference, pinned])
    search, _ = _make_search_service(redis=redis)
    asm, _ = _make_assembler()
    asm._memory_search = search
    with patch("metronix.memory.search.get_agent_memories", return_value=[]):
        context = await asm.assemble("agent1", "ws1", "status update", session_id="shared")
    assert context.memories_count == 1
    assert "status update for this agent" in context.system_prompt
    assert "secret" not in context.system_prompt


async def test_graph_hydration_cannot_bypass_cached_record_filters() -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from metronix.core.models import MemoryKind, MemoryScope

    own = _record("own", "content without query substring")
    invalid = [
        replace(own, id="foreign", agent_id="agent2"),
        replace(own, id="pref", kind=MemoryKind.PREFERENCE),
        replace(own, id="pin", kind=MemoryKind.PINNED),
        replace(own, id="workspace", workspace_id="ws2"),
        replace(own, id="scope", scope=MemoryScope.GLOBAL),
    ]
    redis = MagicMock()
    redis.list = AsyncMock(return_value=[own, *invalid])
    search, _ = _make_search_service(redis=redis)
    # Even misleading graph metadata must not authorize cached content.
    nodes = [{"id": record.id, "agent_id": "agent1"} for record in [own, *invalid]]
    with patch("metronix.memory.search.get_agent_memories", return_value=nodes):
        results = await search.hybrid_search(
            "ws1",
            "unmatched",
            agent_id="agent1",
            session_id="shared",
            kind_filter=[MemoryKind.FACT],
            scope=MemoryScope.PER_AGENT,
        )
    assert [result.record.id for result in results] == ["own"]


async def test_session_and_hydration_preserve_requested_kind_and_metadata() -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from metronix.core.models import MemoryKind

    preference = replace(_record("pref", "query text"), kind=MemoryKind.PREFERENCE)
    redis = MagicMock()
    redis.list = AsyncMock(return_value=[preference])
    search, _ = _make_search_service(redis=redis)
    with patch("metronix.memory.search.get_agent_memories", return_value=[{"id": "pref"}]):
        results = await search.hybrid_search(
            "ws1",
            "query",
            agent_id="agent1",
            session_id="shared",
            kind_filter=[MemoryKind.PREFERENCE],
        )
    assert len(results) == 1
    assert results[0].record.kind == MemoryKind.PREFERENCE
    assert results[0].record.agent_id == "agent1"
