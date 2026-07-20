"""PostgreSQL persistence for temporary conversation events and session ledgers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text

from metronix.memory.conversation_models import ConversationEvent, SessionLedger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


EventRetentionPolicy = Literal["24h", "7d", "30d", "forever"]

_EVENT_RETENTION: dict[EventRetentionPolicy, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "forever": None,
}
_CREDENTIAL_PATTERN = re.compile(
    r"""(?ix)
    \b(?:api[ _-]?key|access[ _-]?token|authorization|bearer|password|passwd|
       secret|client[ _-]?secret|private[ _-]?key)\b
    \s*(?:=|:)\s*(?:bearer\s+)?\S+
    """
)
_KNOWN_CREDENTIAL_PATTERN = re.compile(
    r"""(?x)
    (?:\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9_]{20,}\b|
       \bgithub_pat_[A-Za-z0-9_]{20,}\b|\bsk-[A-Za-z0-9_-]{20,}\b|
       -----BEGIN [A-Z ]*PRIVATE KEY-----)
    """
)
_EMBEDDED_INSTRUCTION_PATTERN = re.compile(
    r"""(?ix)
    \b(?:ignore|disregard|forget|override)\s+(?:all\s+)?
    (?:previous|prior|earlier)\s+(?:instructions?|prompts?|rules?)\b
    |\b(?:reveal|disclose|print|show)\s+(?:the\s+)?
    (?:system|developer)\s+(?:prompt|message|instructions?)\b
    """
)


class UnsafeConversationContentError(ValueError):
    """Raised when an event contains content unsafe for temporary retention."""


def _validate_event_content(content: str) -> None:
    """Reject credential material and embedded prompt-injection directives locally."""
    if (
        _CREDENTIAL_PATTERN.search(content)
        or _KNOWN_CREDENTIAL_PATTERN.search(content)
        or _EMBEDDED_INSTRUCTION_PATTERN.search(content)
    ):
        raise UnsafeConversationContentError("unsafe conversation event content")


def _as_aware(value: Any) -> datetime:
    """Return a UTC-aware timestamp, tolerating legacy naive PostgreSQL values."""
    timestamp: datetime = value
    return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp


def _event_from_row(row: Any) -> ConversationEvent:
    """Convert a PostgreSQL row mapping to a temporary event."""
    return ConversationEvent(
        id=row["id"],
        workspace_id=row["workspace_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        content_hash=row["content_hash"],
        created_at=_as_aware(row["created_at"]),
    )


def _ledger_from_row(row: Any) -> SessionLedger:
    """Convert a PostgreSQL row mapping to a durable session ledger."""
    summary = row["summary"]
    source_hashes = row["source_hashes"]
    return SessionLedger(
        id=row["id"],
        workspace_id=row["workspace_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        summary=summary if isinstance(summary, dict) else json.loads(summary),
        source_hashes=(
            list(source_hashes) if isinstance(source_hashes, list) else json.loads(source_hashes)
        ),
        created_at=_as_aware(row["created_at"]),
        generation=int(row["generation"]),
    )


class ConversationPostgresStore:
    """Async, workspace-scoped store for event content and ledger provenance."""

    def __init__(
        self, engine: AsyncEngine, *, retention_policy: EventRetentionPolicy = "7d"
    ) -> None:
        if retention_policy not in _EVENT_RETENTION:
            raise ValueError(f"unsupported event retention policy: {retention_policy}")
        self._engine = engine
        self._event_retention = _EVENT_RETENTION[retention_policy]

    async def append_event(self, event: ConversationEvent) -> ConversationEvent:
        """Append one safe temporary event; retries with the same id are idempotent."""
        _validate_event_content(event.content)
        expires_at = (
            None if self._event_retention is None else event.created_at + self._event_retention
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO conversation_events (
                        id, workspace_id, agent_id, session_id, role, content,
                        content_hash, created_at, expires_at
                    ) VALUES (
                        :id, :workspace_id, :agent_id, :session_id, :role, :content,
                        :content_hash, :created_at, :expires_at
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": event.id,
                    "workspace_id": event.workspace_id,
                    "agent_id": event.agent_id,
                    "session_id": event.session_id,
                    "role": event.role,
                    "content": event.content,
                    "content_hash": event.content_hash,
                    "created_at": event.created_at,
                    "expires_at": expires_at,
                },
            )
        return event

    async def list_uncompacted(
        self, workspace_id: str, agent_id: str, session_id: str
    ) -> list[ConversationEvent]:
        """Return uncompacted event content for exactly one agent session."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT id, workspace_id, agent_id, session_id, role, content,
                           content_hash, created_at
                    FROM conversation_events
                    WHERE workspace_id = :workspace_id
                      AND agent_id = :agent_id
                      AND session_id = :session_id
                      AND compacted_at IS NULL
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "session_id": session_id,
                },
            )
            rows = result.fetchall()
        return [_event_from_row(row._mapping) for row in rows]

    async def save_ledger(self, ledger: SessionLedger) -> SessionLedger:
        """Persist durable provenance for a session generation without event content."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO session_ledgers (
                        id, workspace_id, agent_id, session_id, generation,
                        summary, source_hashes, created_at
                    ) VALUES (
                        :id, :workspace_id, :agent_id, :session_id, :generation,
                        CAST(:summary AS jsonb), CAST(:source_hashes AS jsonb), :created_at
                    )
                    ON CONFLICT (workspace_id, agent_id, session_id, generation)
                    DO UPDATE SET
                        summary = EXCLUDED.summary,
                        source_hashes = EXCLUDED.source_hashes
                    """
                ),
                {
                    "id": ledger.id,
                    "workspace_id": ledger.workspace_id,
                    "agent_id": ledger.agent_id,
                    "session_id": ledger.session_id,
                    "generation": ledger.generation,
                    "summary": json.dumps(ledger.summary),
                    "source_hashes": json.dumps(ledger.source_hashes),
                    "created_at": ledger.created_at,
                },
            )
        return ledger

    async def get_ledger(
        self, workspace_id: str, agent_id: str, session_id: str
    ) -> SessionLedger | None:
        """Return the latest durable ledger generation for one agent session."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT id, workspace_id, agent_id, session_id, generation,
                           summary, source_hashes, created_at
                    FROM session_ledgers
                    WHERE workspace_id = :workspace_id
                      AND agent_id = :agent_id
                      AND session_id = :session_id
                    ORDER BY generation DESC, created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "session_id": session_id,
                },
            )
            row = result.first()
        return None if row is None else _ledger_from_row(row._mapping)

    async def expire_events(self, *, older_than: datetime) -> int:
        """Delete only expired event content rows; ledgers remain permanently intact."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM conversation_events "
                    "WHERE expires_at IS NOT NULL AND expires_at < :older_than"
                ),
                {"older_than": older_than},
            )
        return int(result.rowcount or 0)
