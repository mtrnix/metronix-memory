"""Local, fail-closed policy for durable conversation-compaction candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from metronix.core.models import LifecycleStatus, MemoryKind
from metronix.storage.conversation_postgres import (  # Task-1 safety boundary is authoritative.
    UnsafeConversationContentError,
    _validate_event_content,
)


class Decision(StrEnum):
    """Whether a candidate can be written as durable agent memory."""

    ACCEPT = "accept"
    REJECT = "reject"


@dataclass(frozen=True)
class MemoryCandidate:
    """Structured, model-independent input to the compaction write policy."""

    content: str
    explicit: bool = False
    kind: MemoryKind = MemoryKind.FACT


@dataclass(frozen=True)
class CandidateEvaluation:
    """Policy decision that deliberately carries no rejected content."""

    decision: Decision
    status: LifecycleStatus | None = None


_TEMPORARY_CHATTER = frozenset(
    {
        "bye",
        "goodbye",
        "got it",
        "hello",
        "hi",
        "okay",
        "ok",
        "thank you",
        "thanks",
    }
)


def evaluate_candidate(
    candidate: MemoryCandidate | str,
    *,
    explicit: bool = False,
    kind: MemoryKind = MemoryKind.FACT,
) -> CandidateEvaluation:
    """Accept only safe durable candidate content without logging rejected text.

    The safety validation is shared with temporary conversation events so the
    durable path cannot reintroduce credentials or untrusted instructions that
    Task 1 rejected at capture time.
    """
    candidate = (
        MemoryCandidate(candidate, explicit=explicit, kind=kind)
        if isinstance(candidate, str)
        else candidate
    )
    if not candidate.content.strip() or candidate.content.strip().casefold() in _TEMPORARY_CHATTER:
        return CandidateEvaluation(Decision.REJECT)

    try:
        _validate_event_content(candidate.content)
    except UnsafeConversationContentError:
        return CandidateEvaluation(Decision.REJECT)

    status = LifecycleStatus.ACTIVE if candidate.explicit else LifecycleStatus.CANDIDATE
    return CandidateEvaluation(Decision.ACCEPT, status)
