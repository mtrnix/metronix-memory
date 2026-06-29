"""Request-scoped ``agent_id`` for activity logging.

Read by emission points in the MCP tool wrapper and in
``retrieval/search.hybrid_search_and_answer``. Written by
``api.middleware.agent_id.AgentIdContextMiddleware``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

current_agent_id: ContextVar[str | None] = ContextVar("current_agent_id", default=None)


def bind_agent_id(agent_id: str | None) -> Token[str | None]:
    """Set the current agent_id. Caller must ``reset(token)`` to avoid leaks."""
    return current_agent_id.set(agent_id)
