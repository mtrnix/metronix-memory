"""Deterministic, policy-gated compaction for temporary conversation events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from metronix.core.config import Settings, get_settings
from metronix.core.models import LifecycleStatus, MemoryRecord
from metronix.memory.compaction_policy import MemoryCandidate, evaluate_candidate
from metronix.memory.conversation_models import (
    ConversationCompactionClaim,
    ConversationEvent,
    SessionLedger,
)

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

    version = "fixture_v1"

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
        claim = await self._events.claim_uncompacted_batch(
            workspace_id,
            agent_id,
            session_id,
            max_events=self._settings.conversation_compaction_max_events,
        )
        if claim is None:
            return CompactionResult(ledger=None)
        try:
            return await self._compact_claim(claim)
        except Exception:
            await self._events.release_claim(claim)
            raise

    async def maybe_compact(
        self,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> CompactionResult | None:
        """Run the event-budget trigger only when automatic compaction is enabled."""
        del workspace_id, agent_id, session_id
        # Capture-triggered compaction remains deliberately disabled. The claim
        # lifecycle protects explicit requests only; no automatic trigger is
        # wired until a separately reviewed worker contract exists.
        return None

    async def _compact_claim(self, claim: ConversationCompactionClaim) -> CompactionResult:
        """Persist one bounded batch after validating event scope and candidates."""
        workspace_id = claim.workspace_id
        agent_id = claim.agent_id
        session_id = claim.session_id
        batch = list(claim.events)
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
        await self._events.finalize_claim(claim, ledger)
        return CompactionResult(
            ledger=ledger,
            memory_records=records,
            rejected_count=rejected_count,
        )
