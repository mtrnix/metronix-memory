"""ASOC session-based auth — Option B validation (MTRNIX-370 Phase 2a, T4).

Replaces the previous HS256 JWT-based ``asoc_jwt.py``.  Instead of verifying a
JWT, Metatron validates the ``X-ASOC-Session: <session_id>`` header that the ASOC
frontend sends on every request.

Validation (Option B from ASOC_API_CONTRACT.md §3.1):
1. Call the ASOC MCP server's ``asoc_get_current_user`` tool in user mode
   (``X-Api-Token: <admin_token>`` + ``X-ASOC-Session: <session_id>``).
2. ASOC's ``withAuth`` middleware validates the session and resolves the user.
3. The tool response contains the user identity; we cache
   ``session_id → AsocAuthContext`` for ``asoc_session_cache_ttl_seconds``.

Cache design (``AsocSessionAuth``):
- One dict-of-dicts in process; entries expire after TTL.
- Soft cap: 10 000 entries.  LRU-style eviction drops oldest 25 % when exceeded.
- Protected by a single ``asyncio.Lock`` (consistent with ``AsocMcpClient``).

FastAPI dependency ``asoc_chat_auth``:
- Reads ``X-ASOC-Session`` from request headers.
- Returns ``AsocAuthContext`` on success.
- Returns 401 on missing / invalid / expired session.
- Returns 503 if admin_token (``ASOC_MCP_ADMIN_TOKEN``) is not configured.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from metatron.integrations.asoc_mcp_client import AsocMcpClient

logger = structlog.get_logger(__name__)

__all__ = [
    "AsocAuthContext",
    "AsocSessionAuth",
    "asoc_chat_auth",
]

# ---------------------------------------------------------------------------
# Auth context (replaces the JWT-based one in asoc_jwt.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AsocAuthContext:
    """Verified ASOC session context forwarded to the chat orchestrator.

    All fields are extracted from the ``asoc_get_current_user`` MCP tool
    response.  ``session_id`` is forwarded verbatim to ASOC MCP / visibility
    filter calls.
    """

    session_id: str  # raw ASOC session ID, forwarded to T5/T6
    user_id: str  # from field 'id' in asoc_get_current_user response
    username: str  # from field 'username'
    display_name: str  # from field 'display_name'
    email: str  # from field 'email'
    roles: list[str]  # from field 'roles' (list of role strings)


# ---------------------------------------------------------------------------
# In-process session cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    context: AsocAuthContext
    expires_at: float  # time.monotonic()


class AsocSessionAuth:
    """In-process TTL cache for ``session_id → AsocAuthContext``.

    Shared across all requests for the lifetime of the app.  Validates unknown
    sessions by calling the ASOC MCP ``asoc_get_current_user`` tool.

    Thread-safety: all mutations go through ``_lock`` (asyncio.Lock).
    """

    _CACHE_SOFT_CAP = 10_000

    def __init__(
        self,
        mcp_client: AsocMcpClient,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._mcp_client = mcp_client
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def validate(self, session_id: str) -> AsocAuthContext:
        """Validate ``session_id`` and return the cached or freshly fetched context.

        Args:
            session_id: The ASOC session ID from the ``X-ASOC-Session`` header.

        Returns:
            :class:`AsocAuthContext` on success.

        Raises:
            HTTPException 401: session_id is empty, expired, or ASOC rejected it.
            HTTPException 503: ASOC MCP admin token not configured.
            HTTPException 502: ASOC MCP server unreachable.
        """
        if not session_id or not session_id.strip():
            raise HTTPException(status_code=401, detail="missing_session_id")

        # Cache hit.
        async with self._lock:
            entry = self._cache.get(session_id)
            if entry and time.monotonic() < entry.expires_at:
                logger.debug("asoc.session_auth.cache_hit", session_id=session_id)
                return entry.context

        # Cache miss — validate with ASOC MCP.
        context = await self._fetch_context(session_id)

        async with self._lock:
            self._evict_if_needed()
            self._cache[session_id] = _CacheEntry(
                context=context,
                expires_at=time.monotonic() + self._ttl,
            )

        return context

    async def _fetch_context(self, session_id: str) -> AsocAuthContext:
        """Call ``asoc_get_current_user`` via MCP and parse the result.

        Raises:
            HTTPException 401: ASOC returned auth error (invalid/expired session).
            HTTPException 502: ASOC MCP unreachable or returned malformed response.
        """
        from metatron.integrations.asoc_mcp_client import McpAuthError, McpUnavailableError

        try:
            result = await self._mcp_client.invoke(
                session_id=session_id,
                tool_name="asoc_get_current_user",
                arguments={},
            )
        except McpAuthError as exc:
            logger.warning("asoc.session_auth.rejected", session_id=session_id, reason=str(exc))
            raise HTTPException(status_code=401, detail="invalid_or_expired_session") from exc
        except McpUnavailableError as exc:
            logger.error(
                "asoc.session_auth.mcp_unreachable", session_id=session_id, error=str(exc)
            )
            raise HTTPException(status_code=502, detail="asoc_mcp_unreachable") from exc
        except Exception as exc:
            logger.error(
                "asoc.session_auth.unexpected_error", session_id=session_id, error=str(exc)
            )
            raise HTTPException(status_code=502, detail="asoc_mcp_error") from exc

        # Parse response: content is a list of MCP content blocks.
        # asoc_get_current_user returns {id, username, display_name, email, roles, session_id}
        try:
            payload = _extract_json_from_content(result.content)
            user_id = str(payload["id"])
            username = str(payload.get("username") or "")
            display_name = str(payload.get("display_name") or "")
            email = str(payload.get("email") or "")
            roles_raw = payload.get("roles") or []
            roles = [str(r) for r in roles_raw] if isinstance(roles_raw, list) else []
        except (KeyError, TypeError, ValueError) as exc:
            logger.error(
                "asoc.session_auth.malformed_response",
                session_id=session_id,
                content=result.content,
                error=str(exc),
            )
            raise HTTPException(status_code=502, detail="asoc_mcp_malformed_response") from exc

        logger.info(
            "asoc.session_auth.validated",
            user_id=user_id,
            username=username,
        )
        return AsocAuthContext(
            session_id=session_id,
            user_id=user_id,
            username=username,
            display_name=display_name,
            email=email,
            roles=roles,
        )

    def _evict_if_needed(self) -> None:
        """Drop oldest 25 % of cache entries when the soft cap is exceeded.

        Must be called while holding ``_lock``.
        """
        if len(self._cache) > self._CACHE_SOFT_CAP:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k].expires_at)
            drop_count = max(1, len(sorted_keys) // 4)
            for k in sorted_keys[:drop_count]:
                del self._cache[k]
            logger.debug(
                "asoc.session_auth.cache.evicted",
                dropped=drop_count,
                remaining=len(self._cache),
            )

    def invalidate(self, session_id: str) -> None:
        """Remove a cached session (e.g. on explicit logout).  No-op if absent."""
        self._cache.pop(session_id, None)


# ---------------------------------------------------------------------------
# Helper: extract JSON from MCP content blocks
# ---------------------------------------------------------------------------


def _extract_json_from_content(content: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the first JSON-decodable text block in a list of MCP content blocks.

    MCP content blocks look like ``[{"type": "text", "text": "<json string>"}]``
    or ``[{"type": "json", "data": {...}}]``.

    Raises:
        ValueError: No parseable block found.
    """
    for block in content:
        # "json" type with raw dict under "data"
        if block.get("type") == "json":
            data = block.get("data")
            if isinstance(data, dict):
                return data  # type: ignore[return-value]

        # "text" type with JSON string under "text"
        text = block.get("text")
        if isinstance(text, str) and text.strip().startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed  # type: ignore[return-value]
            except json.JSONDecodeError:
                continue

    raise ValueError(f"no parseable JSON block found in MCP content: {content!r}")


# ---------------------------------------------------------------------------
# FastAPI dependency for chat + thread endpoints
# ---------------------------------------------------------------------------


async def asoc_chat_auth(request: Request) -> AsocAuthContext:
    """FastAPI ``Depends`` that validates the ``X-ASOC-Session`` header.

    Reads the session authenticator from ``app.state.asoc_session_auth``.

    Returns:
        :class:`AsocAuthContext` on success.

    Raises:
        HTTPException 503: ``asoc_session_auth`` not initialised (admin token
            not configured or app not fully started).
        HTTPException 401: ``X-ASOC-Session`` header missing or session invalid.
    """
    session_auth: AsocSessionAuth | None = getattr(request.app.state, "asoc_session_auth", None)
    if session_auth is None:
        logger.warning("asoc_chat_auth.not_configured")
        raise HTTPException(status_code=503, detail="asoc_session_auth_not_configured")

    session_id = request.headers.get("X-ASOC-Session", "")
    if not session_id:
        raise HTTPException(status_code=401, detail="missing_x_asoc_session_header")

    return await session_auth.validate(session_id)
