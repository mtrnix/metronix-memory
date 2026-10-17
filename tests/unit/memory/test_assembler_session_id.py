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
