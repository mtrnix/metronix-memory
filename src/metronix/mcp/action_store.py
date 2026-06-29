"""In-memory store for pending MCP write actions awaiting user confirmation.

Each action has a TTL (default 5 minutes). Expired actions are cleaned
up on access. One pending action per user at a time.
"""

from __future__ import annotations

import time
import uuid

import structlog

logger = structlog.get_logger()


class PendingAction:
    """A write action waiting for user confirmation.

    Attributes:
        action_id: Unique identifier.
        user_id: Channel user who initiated the action.
        server_name: MCP server to execute on.
        tool_name: Tool to call.
        arguments: Tool input parameters.
        description: Short human-readable summary (1 sentence).
        preview: Detailed preview of what will happen.
        created_at: Timestamp when created.
        ttl_seconds: Time-to-live before auto-expiry.
    """

    def __init__(
        self,
        user_id: str,
        server_name: str,
        tool_name: str,
        arguments: dict,
        description: str,
        preview: str,
        ttl_seconds: int = 300,
    ) -> None:
        self.action_id: str = uuid.uuid4().hex[:12]
        self.user_id = user_id
        self.server_name = server_name
        self.tool_name = tool_name
        self.arguments = arguments
        self.description = description
        self.preview = preview
        self.created_at: float = time.time()
        self.ttl_seconds = ttl_seconds

    @property
    def expired(self) -> bool:
        """Whether this action has exceeded its TTL."""
        return time.time() - self.created_at > self.ttl_seconds


class ActionStore:
    """In-memory store for pending actions awaiting confirmation.

    Thread-safe for single-writer patterns (one bot message at a time).
    Expired actions are cleaned up lazily on access.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}

    def add(self, action: PendingAction) -> str:
        """Store a pending action.

        Args:
            action: The action to store.

        Returns:
            The action ID.
        """
        self._cleanup_expired()
        self._pending[action.action_id] = action
        logger.info(
            "action_store.added",
            action_id=action.action_id,
            user_id=action.user_id,
            tool=action.tool_name,
        )
        return action.action_id

    def get_for_user(self, user_id: str) -> PendingAction | None:
        """Get the most recent non-expired pending action for a user.

        Args:
            user_id: The user to look up.

        Returns:
            PendingAction if found, None otherwise.
        """
        self._cleanup_expired()
        for action in reversed(list(self._pending.values())):
            if action.user_id == user_id and not action.expired:
                return action
        return None

    def remove(self, action_id: str) -> PendingAction | None:
        """Remove and return a pending action.

        Args:
            action_id: The action to remove.

        Returns:
            The removed action, or None if not found.
        """
        return self._pending.pop(action_id, None)

    def _cleanup_expired(self) -> None:
        """Remove all expired actions."""
        expired = [k for k, v in self._pending.items() if v.expired]
        for k in expired:
            del self._pending[k]
        if expired:
            logger.debug("action_store.cleanup", removed=len(expired))


# Module-level singleton
_action_store: ActionStore | None = None


def get_action_store() -> ActionStore:
    """Get or create the global ActionStore singleton."""
    global _action_store  # noqa: PLW0603
    if _action_store is None:
        _action_store = ActionStore()
    return _action_store
