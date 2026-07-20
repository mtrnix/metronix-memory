"""Data shapes for temporary conversation events and durable session ledgers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass
class ConversationEvent:
    """One temporary, append-only message captured for a conversation session."""

    id: str
    workspace_id: str
    agent_id: str
    session_id: str
    role: str
    content: str
    content_hash: str
    created_at: datetime

    @classmethod
    def new(
        cls,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> ConversationEvent:
        """Create an event with a stable content hash for ledger provenance."""
        return cls(
            id=uuid4().hex,
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            role=role,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            created_at=datetime.now(UTC),
        )


@dataclass
class SessionLedger:
    """Durable compaction provenance for one generation of a conversation session."""

    id: str
    workspace_id: str
    agent_id: str
    session_id: str
    summary: dict[str, object] = field(default_factory=dict)
    source_hashes: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    generation: int = 0

    @classmethod
    def new(
        cls,
        event: ConversationEvent,
        *,
        source_hashes: list[str],
        summary: dict[str, object] | None = None,
        generation: int = 0,
    ) -> SessionLedger:
        """Start a ledger from an event while retaining only content provenance."""
        return cls(
            id=uuid4().hex,
            workspace_id=event.workspace_id,
            agent_id=event.agent_id,
            session_id=event.session_id,
            summary={} if summary is None else summary,
            source_hashes=list(source_hashes),
            generation=generation,
        )
