"""Per-user conversation session management.

Stores recent messages per user+workspace in memory (MVP).
Builds composite queries from recent conversation context for better search.
Thread-safe for use from sync AgentRouter called via asyncio.to_thread().

Production: move to PostgreSQL or Redis for persistence.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

DEFAULT_MAX_HISTORY = 20
DEFAULT_MAX_COMPOSITE_TURNS = 3


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


class SessionManager:
    """Thread-safe in-memory conversation session store.

    Keyed by (channel_user_id, workspace_id). Stores the last N turns
    for LLM context. Provides composite query building from recent context.

    Not persistent across restarts — MVP design.
    """

    _instance: SessionManager | None = None
    _init_lock = threading.Lock()

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY) -> None:
        self._max_history = max_history
        self._sessions: dict[str, list[ConversationTurn]] = defaultdict(list)
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls, max_history: int = DEFAULT_MAX_HISTORY) -> SessionManager:
        """Singleton accessor — safe for multi-threaded use."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls(max_history=max_history)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        with cls._init_lock:
            cls._instance = None

    def _key(self, user_id: str, workspace_id: str) -> str:
        return f"{user_id}:{workspace_id}"

    def get_history(self, user_id: str, workspace_id: str) -> list[dict[str, str]]:
        """Get conversation history as list of role/content dicts.

        Thread-safe. Returns a copy.
        """
        key = self._key(user_id, workspace_id)
        with self._lock:
            turns = list(self._sessions[key])
        return [{"role": t.role, "content": t.content} for t in turns]

    def add_turn(self, user_id: str, workspace_id: str, role: str, content: str) -> None:
        """Add a conversation turn. Trims to max_history (FIFO). Thread-safe."""
        key = self._key(user_id, workspace_id)
        turn = ConversationTurn(role=role, content=content)
        with self._lock:
            self._sessions[key].append(turn)
            if len(self._sessions[key]) > self._max_history:
                self._sessions[key] = self._sessions[key][-self._max_history:]

    def clear(self, user_id: str, workspace_id: str) -> None:
        """Clear conversation history for a user. Thread-safe."""
        key = self._key(user_id, workspace_id)
        with self._lock:
            self._sessions.pop(key, None)

    def build_composite_query(
        self,
        user_id: str,
        workspace_id: str,
        current_query: str,
        max_turns: int = DEFAULT_MAX_COMPOSITE_TURNS,
    ) -> str:
        """Build a composite query from recent conversation context.

        Takes the last N user messages and combines them with the current query
        for better search context. Useful when users send follow-up questions
        like "what about their deadlines?" after asking about a specific team.

        Args:
            user_id: Channel-specific user ID.
            workspace_id: Current workspace.
            current_query: The current user message.
            max_turns: How many recent user turns to include.

        Returns:
            Composite query string with context, or just current_query if no history.
        """
        key = self._key(user_id, workspace_id)
        with self._lock:
            turns = list(self._sessions[key])

        # Collect recent user messages (excluding current)
        user_msgs = [t.content for t in turns if t.role == "user"]
        recent = user_msgs[-max_turns:] if len(user_msgs) > max_turns else user_msgs

        if not recent:
            return current_query

        # Combine: "context: <recent> | question: <current>"
        context = " | ".join(recent)
        return f"context: {context} | question: {current_query}"
