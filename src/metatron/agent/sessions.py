"""Per-user conversation history management.

Stores recent messages per user+workspace in memory (MVP).
Production: move to PostgreSQL or Redis for persistence.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

logger = structlog.get_logger()

DEFAULT_MAX_HISTORY = 20


class SessionStore:
    """In-memory conversation history store.

    Keyed by (channel_user_id, workspace_id). Stores the last
    N messages for LLM context. Not persistent across restarts.
    """

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY) -> None:
        self._max_history = max_history
        self._sessions: dict[str, list[dict[str, str]]] = defaultdict(list)

    def _key(self, user_id: str, workspace_id: str) -> str:
        return f"{user_id}:{workspace_id}"

    async def get_history(
        self, user_id: str, workspace_id: str
    ) -> list[dict[str, str]]:
        """Get conversation history for a user in a workspace.

        Args:
            user_id: Channel-specific user ID.
            workspace_id: Current workspace.

        Returns:
            List of message dicts [{"role": "user"|"assistant", "content": "..."}].
        """
        key = self._key(user_id, workspace_id)
        return list(self._sessions[key])

    async def add_message(
        self, user_id: str, workspace_id: str, role: str, content: str
    ) -> None:
        """Add a message to the conversation history.

        Trims to max_history if needed (FIFO).

        Args:
            user_id: Channel-specific user ID.
            workspace_id: Current workspace.
            role: "user" or "assistant".
            content: Message text.
        """
        key = self._key(user_id, workspace_id)
        self._sessions[key].append({"role": role, "content": content})
        if len(self._sessions[key]) > self._max_history:
            self._sessions[key] = self._sessions[key][-self._max_history :]

    async def clear(self, user_id: str, workspace_id: str) -> None:
        """Clear conversation history for a user."""
        key = self._key(user_id, workspace_id)
        self._sessions.pop(key, None)
