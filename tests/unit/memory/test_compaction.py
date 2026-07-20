"""Unit coverage for deterministic conversation compaction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.core.config import Settings
from metronix.core.models import LifecycleStatus, MemoryKind, MemoryRecord, MemoryScope
from metronix.memory.compaction import CompactionController, DeterministicFixtureExtractor
from metronix.memory.compaction_policy import MemoryCandidate
from metronix.memory.conversation_models import ConversationEvent
from metronix.memory.service import MemoryService


def _event() -> ConversationEvent:
    return ConversationEvent.new("ws", "agent-a", "s-1", "user", "hello")


def _record(content: str, status: LifecycleStatus) -> MemoryRecord:
    return MemoryRecord(
        workspace_id="ws",
        agent_id="agent-a",
        scope=MemoryScope.PER_AGENT,
        kind=MemoryKind.FACT,
        source_type="conversation_compaction",
        content=content,
        status=status,
    )


@pytest.fixture
def event_store() -> MagicMock:
    store = MagicMock()
    store.list_uncompacted = AsyncMock(return_value=[_event()])
    store.get_ledger = AsyncMock(return_value=None)
    store.save_ledger = AsyncMock(side_effect=lambda ledger: ledger)
    return store


@pytest.fixture
def memory_service() -> MagicMock:
    service = MagicMock()

    async def _save_compaction_memory(
        workspace_id: str,
        *,
        agent_id: str,
        content: str,
        kind: MemoryKind,
        status: LifecycleStatus,
        session_id: str,
        source_hashes: list[str],
    ) -> MemoryRecord:
        assert workspace_id == "ws"
        assert agent_id == "agent-a"
        assert session_id == "s-1"
        assert source_hashes
        return _record(content, status)

    service.save_compaction_memory = AsyncMock(side_effect=_save_compaction_memory)
    return service


async def test_compact_writes_candidate_and_private_ledger(
    event_store: MagicMock, memory_service: MagicMock
) -> None:
    """The controller writes policy-approved candidates privately with hash-only provenance."""
    controller = CompactionController(
        event_store,
        memory_service,
        extractor=DeterministicFixtureExtractor(
            [MemoryCandidate(content="The project uses PostgreSQL")]
        ),
    )

    result = await controller.compact("ws", "agent-a", "s-1", reason="session_end")

    assert result.ledger is not None
    assert result.ledger.agent_id == "agent-a"
    assert result.memory_records[0].scope is MemoryScope.PER_AGENT
    assert result.memory_records[0].status is LifecycleStatus.CANDIDATE
    assert result.ledger.summary["extractor_version"] == "deterministic-fixture-v1"
    assert "hello" not in str(result.ledger.summary)
    event_store.save_ledger.assert_awaited_once_with(result.ledger)
    memory_service.save_compaction_memory.assert_awaited_once()


async def test_compact_rejects_unsafe_candidate_without_persisting_it(
    event_store: MagicMock, memory_service: MagicMock
) -> None:
    """Rejected content is neither written nor included in the durable ledger."""
    controller = CompactionController(
        event_store,
        memory_service,
        extractor=DeterministicFixtureExtractor(
            [MemoryCandidate(content="token: abcdefghijklmnopqrstuvwx")]
        ),
    )

    result = await controller.compact("ws", "agent-a", "s-1", reason="session_end")

    assert result.rejected_count == 1
    assert result.memory_records == []
    memory_service.save_compaction_memory.assert_not_awaited()
    saved_ledger = event_store.save_ledger.await_args.args[0]
    assert "abcdefgh" not in str(saved_ledger.summary)


async def test_maybe_compact_is_a_noop_when_automatic_compaction_is_disabled(
    event_store: MagicMock, memory_service: MagicMock
) -> None:
    """Feature-disabled deployments never run automatic compaction."""
    controller = CompactionController(
        event_store,
        memory_service,
        settings=Settings(),
    )

    result = await controller.maybe_compact("ws", "agent-a", "s-1")

    assert result is None
    event_store.list_uncompacted.assert_not_awaited()


async def test_save_compaction_memory_is_private_and_rechecks_unsafe_content() -> None:
    """The MemoryService integration cannot bypass the controller's safety policy."""
    service = MemoryService(
        redis_cache=MagicMock(),
        qdrant_store=MagicMock(),
        pg_store=MagicMock(),
        workspace_id="ws",
    )
    service.save = AsyncMock(side_effect=lambda workspace_id, record: record)  # type: ignore[method-assign]

    record = await service.save_compaction_memory(
        "ws",
        agent_id="agent-a",
        content="The project uses PostgreSQL",
        kind=MemoryKind.FACT,
        status=LifecycleStatus.CANDIDATE,
        session_id="s-1",
        source_hashes=["a" * 64],
    )

    assert record.scope is MemoryScope.PER_AGENT
    assert record.status is LifecycleStatus.CANDIDATE
    assert record.metadata == {
        "compaction": {"source_session_id": "s-1", "source_hashes": ["a" * 64]}
    }

    with pytest.raises(ValueError):
        await service.save_compaction_memory(
            "ws",
            agent_id="agent-a",
            content="api_key=secret",
            kind=MemoryKind.FACT,
            status=LifecycleStatus.CANDIDATE,
            session_id="s-1",
            source_hashes=["a" * 64],
        )

    assert service.save.await_count == 1


def test_compaction_settings_are_safe_by_default() -> None:
    """Automatic compaction is opt-in and raw event retention remains seven days."""
    settings = Settings()

    assert settings.conversation_compaction_enabled is False
    assert settings.conversation_event_retention == "7d"
    assert settings.conversation_compaction_max_events > 0
    assert settings.conversation_compaction_idle_minutes > 0
