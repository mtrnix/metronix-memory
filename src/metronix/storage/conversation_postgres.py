"""PostgreSQL persistence for temporary conversation events and session ledgers."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
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
    \b(?:api[ _-]?key|access[ _-]?token|authorization|bearer|token|password|passwd|
       secret|client[ _-]?secret|private[ _-]?key)\b
    \s*(?:=|:|\bis\b)\s*(?:bearer\s+)?\S+
    """
)
_KNOWN_CREDENTIAL_PATTERN = re.compile(
    r"""(?x)
    (?:\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9_]{20,}\b|
       \bgithub_pat_[A-Za-z0-9_]{20,}\b|\bsk-[A-Za-z0-9_-]{20,}\b|
       -----BEGIN [A-Z ]*PRIVATE KEY-----)
    """
)
_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{24,}(?![A-Za-z0-9_+/=-])")
_INSTRUCTION_TARGET_PATTERN = re.compile(
    r"\b(?:system|developer|operating|assistant|model|safety|security|"
    r"rules?|instructions?|prompts?|polic(?:y|ies))\b",
    re.IGNORECASE,
)
_PRECEDENCE_PATTERN = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass|supersede|replace|"
    r"discard|outrank|trump|set\s+aside|take\s+precedence\s+over|"
    r"higher\s+priority\s+than)\b",
    re.IGNORECASE,
)
_ROLE_ESCALATION_PATTERN = re.compile(
    r"\b(?:you|assistant|model|agent)\s+(?:are|will\s+be|must\s+be|"
    r"should\s+be|become)\s+(?:(?:now|henceforth|from\s+now\s+on)\s+)?"
    r"(?:the\s+)?(?:system|developer|root|administrator|admin)\b"
    r"|\bassume\s+the\s+role\s+of\s+(?:the\s+)?"
    r"(?:system|developer|root|administrator|admin)\b"
    r"|(?:^|\n)\s*(?:system|developer)\s*:\s*"
    r"(?:you\s+(?:are|must|will|should)|ignore|disregard|override|"
    r"bypass|supersede|follow|do\s+not)\b",
    re.IGNORECASE,
)
_PRIVILEGED_ROLE_HEADER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:system|developer)\s*:\s*\S",
    re.IGNORECASE,
)
_PROTECTED_DISCLOSURE_PATTERN = re.compile(
    r"""(?ix)
    \b(?:reveal|disclose|print|show|extract|repeat|leak|send|post|upload|transmit)\s+
    (?:the\s+)?(?:hidden\s+|private\s+|internal\s+)?
    (?:system|developer|operating)\s+(?:prompt|messages?|instructions?|rules?|context)\b
    """
)
_SENSITIVE_FIELD_LABEL_PATTERN = re.compile(
    r"""(?ix)^\s*
    (?:api[ _-]?key|access[ _-]?token|authorization|bearer(?:[ _-]?token)?|token|
       password|passwd|secret|client[ _-]?secret|private[ _-]?key)
    \s*$"""
)
_CANONICAL_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class UnsafeConversationContentError(ValueError):
    """Raised when an event contains content unsafe for temporary retention."""


def _shannon_entropy(token: str) -> float:
    """Return the Shannon entropy in bits per character for a candidate token."""
    token_length = len(token)
    return -sum(
        (count / token_length) * math.log2(count / token_length)
        for count in {character: token.count(character) for character in set(token)}.values()
    )


def _contains_credential_like_token(content: str) -> bool:
    """Detect unlabelled high-entropy tokens without rejecting ordinary prose."""
    for token_match in _TOKEN_PATTERN.finditer(content):
        token = token_match.group()
        character_classes = sum(
            (
                any(character.islower() for character in token),
                any(character.isupper() for character in token),
                any(character.isdigit() for character in token),
                any(character in "_+/=-" for character in token),
            )
        )
        if character_classes >= 2 and _shannon_entropy(token) >= 3.5:
            return True
    return False


def _contains_untrusted_instruction(content: str) -> bool:
    """Detect local prompt-injection attempts against protected instructions or roles."""
    return bool(
        _PRIVILEGED_ROLE_HEADER_PATTERN.search(content)
        or _ROLE_ESCALATION_PATTERN.search(content)
        or _PROTECTED_DISCLOSURE_PATTERN.search(content)
        or (_PRECEDENCE_PATTERN.search(content) and _INSTRUCTION_TARGET_PATTERN.search(content))
    )


def _validate_event_content(content: str) -> None:
    """Fail closed on credential-like values and instruction-override attempts locally."""
    if (
        _CREDENTIAL_PATTERN.search(content)
        or _KNOWN_CREDENTIAL_PATTERN.search(content)
        or _contains_credential_like_token(content)
        or _contains_untrusted_instruction(content)
    ):
        raise UnsafeConversationContentError("unsafe conversation event content")


def _validate_ledger_summary_value(value: object, *, field_label: str | None = None) -> None:
    """Reject unsafe durable-summary content recursively before serialization."""
    if (
        field_label is not None
        and _SENSITIVE_FIELD_LABEL_PATTERN.fullmatch(field_label)
        and value is not None
    ):
        raise UnsafeConversationContentError("unsafe conversation ledger summary")

    if isinstance(value, str):
        _validate_event_content(value)
        return
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise UnsafeConversationContentError("unsafe conversation ledger summary")
            _validate_event_content(key)
            _validate_ledger_summary_value(nested_value, field_label=key)
        return
    if isinstance(value, list | tuple):
        for nested_value in value:
            _validate_ledger_summary_value(nested_value, field_label=field_label)
        return
    raise UnsafeConversationContentError("unsafe conversation ledger summary")


def _validate_ledger_summary(summary: dict[str, object]) -> None:
    """Validate all durable summary fields before any database work begins."""
    _validate_ledger_summary_value(summary)


def _validate_ledger_source_hashes(source_hashes: object) -> None:
    """Require durable provenance to contain only canonical SHA-256 digests."""
    if not isinstance(source_hashes, list) or not all(
        isinstance(source_hash, str) and _CANONICAL_SHA256_PATTERN.fullmatch(source_hash)
        for source_hash in source_hashes
    ):
        raise UnsafeConversationContentError("unsafe conversation ledger source hashes")


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
        _validate_ledger_source_hashes(ledger.source_hashes)
        _validate_ledger_summary(ledger.summary)
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
