"""Persistent chat history module (MTRNIX-353, T3).

Public surface — re-exported for convenience by callers that want a single import.
"""

from __future__ import annotations

from metatron.chat.cleanup import ChatCleanupStats, ChatHistoryCleanupWorker
from metatron.chat.models import ChatMessage, ChatMessageRole, ChatThread
from metatron.chat.persistence import ChatPersistence

__all__ = [
    "ChatCleanupStats",
    "ChatHistoryCleanupWorker",
    "ChatMessage",
    "ChatMessageRole",
    "ChatPersistence",
    "ChatThread",
]
