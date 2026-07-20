"""Deterministic, policy-gated compaction for temporary conversation events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from metronix.core.config import Settings, get_settings
from metronix.core.models import LifecycleStatus, MemoryRecord
from metronix.memory.compaction_policy import MemoryCandidate, evaluate_candidate
from metronix.memory.conversation_models import ConversationEvent, SessionLedger

if TYPE_CHECKING:
    from metronix.memory.service import MemoryService
    from metronix.storage.conversation_postgres import ConversationPostgresStore


class CandidateExtractor(Protocol):
    """Produces structured candidate inputs without calling an external model."""

    def extract(self, events: Sequence[ConversationEvent]) -> list[MemoryCandidate]:
        """Return candidate inputs derived from a bounded event batch."""


class DeterministicFixtureExtractor:
    """Testable extractor whose configured candidates never include raw events.

    The production default has no candidates. A future model-backed extractor
    must implement :class:`CandidateExtractor` and is still gated by
    ``evaluate_candidate`` before durable persistence.
    """

    version = "deterministic-fixture-v1"

    def __init__(self, candidates: Sequence[MemoryCandidate] = ()) -> None:
        self._candidates = tuple(candidates)

    def extract(self, events: Sequence[ConversationEvent]) -> list[MemoryCandidate]:
        del events
        return list(self._candidates)


@dataclass(frozen=True)
class CompactionResult:
    """The durable artifacts produced from one compaction attempt."""

    ledger: SessionLedger | None
    memory_records: list[MemoryRecord] = field(default_factory=list)
    rejected_count: int = 0


class CompactionController:
    """Write safe, source-linked candidate memories from a conversation batch."""

    def __init__(
        self,
        events: ConversationPostgresStore,
        memory_service: MemoryService,
        *,
        extractor: CandidateExtractor | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._events = events
        self._memory_service = memory_service
        self._extractor = extractor or DeterministicFixtureExtractor()
        self._settings = settings or get_settings()

    async def compact(
        self,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        *,
        reason: str,
    ) -> CompactionResult:
        """Compact one explicitly requested session batch.

        Explicit callers may compact while automatic compaction remains disabled.
        ``reason`` is intentionally not persisted because it can be caller text;
        durable metadata records only structured counts and source hashes.
        """
        del reason
        events = await self._events.list_uncompacted(workspace_id, agent_id, session_id)
        return await self._compact_events(workspace_id, agent_id, session_id, events)

    async def maybe_compact(
        self,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> CompactionResult | None:
        """Run the event-budget trigger only when automatic compaction is enabled."""
        if not self._settings.conversation_compaction_enabled:
            return None

        events = await self._events.list_uncompacted(workspace_id, agent_id, session_id)
        if len(events) < self._settings.conversation_compaction_max_events:
            return None
        return await self._compact_events(workspace_id, agent_id, session_id, events)

    async def _compact_events(
        self,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        events: Sequence[ConversationEvent],
    ) -> CompactionResult:
        """Persist one bounded batch after validating event scope and candidates."""
        batch = list(events[: self._settings.conversation_compaction_max_events])
        if not batch:
            return CompactionResult(ledger=None)
        if any(
            event.workspace_id != workspace_id
            or event.agent_id != agent_id
            or event.session_id != session_id
            for event in batch
        ):
            raise ValueError("conversation event scope mismatch")

        accepted: list[tuple[MemoryCandidate, LifecycleStatus]] = []
        rejected_count = 0
        for candidate in self._extractor.extract(batch):
            evaluation = evaluate_candidate(candidate)
            status = evaluation.status
            if status is None:
                rejected_count += 1
                continue
            accepted.append((candidate, status))

        latest_ledger = await self._events.get_ledger(workspace_id, agent_id, session_id)
        ledger = SessionLedger.new(
            batch[0],
            source_hashes=[event.content_hash for event in batch],
            summary={
                "goal_or_topic": None,
                "participants": [],
                "decisions": [],
                "commitments": [],
                "preferences": [],
                "facts": [],
                "corrections": [],
                "open_threads": [],
                "next_follow_ups": [],
                "source_event_count": len(batch),
                "extractor_version": getattr(self._extractor, "version", "custom-v1"),
                "confidence": 1.0,
                "candidate_count": len(accepted),
                "rejected_candidate_count": rejected_count,
            },
            generation=0 if latest_ledger is None else latest_ledger.generation + 1,
        )
        await self._events.save_ledger(ledger)

        records: list[MemoryRecord] = []
        source_hashes = list(ledger.source_hashes)
        for candidate, status in accepted:
            record = await self._memory_service.save_compaction_memory(
                workspace_id,
                agent_id=agent_id,
                content=candidate.content,
                kind=candidate.kind,
                status=status,
                session_id=session_id,
                source_hashes=source_hashes,
            )
            records.append(record)
        return CompactionResult(
            ledger=ledger,
            memory_records=records,
            rejected_count=rejected_count,
        )
