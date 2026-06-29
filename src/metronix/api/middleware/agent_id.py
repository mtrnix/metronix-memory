"""X-Agent-Id middleware — populates the ``current_agent_id`` contextvar.

Applied in ``create_app()`` for mounted paths (REST, OpenAI-compat, /mcp) and
separately inside ``mcp/server.py:run_http()`` for the standalone streamable-HTTP
transport (wired in later tasks). Invalid or missing header → contextvar stays
``None``; the request is NOT rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from metronix.activity.context import bind_agent_id, current_agent_id
from metronix.core.utils import is_valid_agent_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)

_HEADER = "X-Agent-Id"


def _validate(value: str | None) -> str | None:
    """Return the header value when it is a valid agent id, else None.

    Uses the shared :func:`is_valid_agent_id` rule (1..64 chars of
    ``A-Za-z0-9._-``) so the MCP header, the registration endpoint, and the
    memory tools all agree on what a usable agent id is.
    """
    if value is None:
        return None
    return value if is_valid_agent_id(value) else None


class AgentIdContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw = request.headers.get(_HEADER)
        value = _validate(raw)
        if raw is not None and value is None:
            logger.warning(
                "agent_id.header_rejected",
                header_len=len(raw),
            )

        token = bind_agent_id(value)
        try:
            return await call_next(request)
        finally:
            current_agent_id.reset(token)
