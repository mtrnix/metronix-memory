"""Data models for the persistent chat history module (MTRNIX-353, T3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 — dataclass fields need runtime resolution
from enum import StrEnum
from typing import Any
from uuid import UUID  # noqa: TC003 — dataclass fields need runtime resolution


class ChatMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass(frozen=True)
class ChatThread:
    """A conversation thread — one per (workspace_id, user_id) in MVP."""

    thread_id: UUID
    workspace_id: str
    user_id: str
    created_at: datetime
    last_message_at: datetime | None


@dataclass(frozen=True)
class ChatMessage:
    """A single message inside a chat thread."""

    id: UUID
    thread_id: UUID
    role: ChatMessageRole
    content: str
    citations_json: list[dict[str, Any]] | None
    tool_calls_json: list[dict[str, Any]] | None
    created_at: datetime
