"""ASOC MCP client — whitelist-gated streamable-HTTP MCP client for ASOC.

T4 (chat orchestrator) uses this client to:
- Discover which ASOC MCP tools are available for the authenticated user.
- Invoke a whitelisted tool on behalf of that user (session forwarded verbatim).

Design decisions:
- **Double gate**: the whitelist is checked in BOTH ``list_available_tools`` (gate A,
  server-side filter) AND ``invoke`` (gate B, pre-dispatch).  Even if the allowlist is
  misconfigured, no write tool reaches the wire via ``invoke``.
- **Session forwarding**: T4 now passes ``session_id`` (ASOC session ID) instead of a
  JWT.  User-mode sends ``X-Api-Token`` + ``X-ASOC-Session`` per ASOC ``withAuth``
  middleware convention (ASOC plan §1.0).  Admin-mode sends ``X-Api-Token`` only.
  The session_id is used directly as a stable per-user cache key (no JWT decoding).
- **Graceful degradation**: ``list_available_tools`` returns ``[]`` on network errors so
  the chat orchestrator can still operate in retrieval-only mode.
- **Per-session TTL cache**: tool lists are cached per session_id for
  ``tool_list_cache_ttl_seconds`` (default 60 s) to avoid hammering ASOC on every turn.
  Soft cap of 1024 entries with LRU-style eviction (drop oldest 25 %).
- **Lazy SDK import**: the ``mcp`` package is imported inside helper methods, matching
  the pattern in ``mcp/client.py``.  Unit tests can mock the session boundary without
  importing the SDK at all.

Exceptions (live in this module, not core/exceptions.py):
    AsocMcpError → ToolNotAllowedError, McpAuthError, McpUnavailableError, McpProtocolError
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import structlog
from pydantic import BaseModel

from metatron.core.asoc_constants import ASOC_MCP_READ_ONLY_TOOLS_DEFAULT

if TYPE_CHECKING:
    from metatron.core.config import Settings

__all__ = [
    "ASOC_MCP_READ_ONLY_TOOLS_DEFAULT",
    "AsocMcpClient",
    "AsocMcpError",
    "AsocToolCallResult",
    "AsocToolDescriptor",
    "McpAuthError",
    "McpProtocolError",
    "McpUnavailableError",
    "ToolNotAllowedError",
]

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AsocMcpError(Exception):
    """Base for all ASOC MCP client errors."""


class ToolNotAllowedError(AsocMcpError):
    """Tool name not in the whitelist — pre-dispatch reject."""


class McpAuthError(AsocMcpError):
    """ASOC returned 401/403 — JWT bad or expired."""


class McpUnavailableError(AsocMcpError):
    """MCP server unreachable (DNS, connect, timeout, 5xx after retries)."""


class McpProtocolError(AsocMcpError):
    """Malformed JSON-RPC response, unexpected envelope, 4xx other than auth."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AsocToolDescriptor(BaseModel):
    """Descriptor for one MCP tool as seen by the LLM."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON-Schema for LLM tool schema


class AsocToolCallResult(BaseModel):
    """Result of a single tool invocation."""

    tool: str
    content: list[dict[str, Any]]  # MCP content blocks
    is_error: bool = False


# ---------------------------------------------------------------------------
# Cache internals
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    tools: list[AsocToolDescriptor]
    expires_at: float  # time.monotonic()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AsocMcpClient:
    """Whitelist-gated MCP client for ASOC's streamable-HTTP MCP server.

    Instantiate once (e.g. at app startup) and share across requests.  The
    internal cache is in-process and not shared across worker replicas — that is
    acceptable given the short TTL (60 s default).

    Args:
        url: Full URL of the ASOC MCP server, e.g.
            ``https://asoc.example.com/mcp``.  Empty string disables the client
            (all methods return safe no-ops / raise immediately).
        allowed_tools: Whitelist of tool names.  Accepts a ``frozenset`` or a
            plain ``list``; both are normalised to ``frozenset`` internally.
        request_timeout_seconds: Per-request timeout (both ``tools/list`` and
            ``tools/call``).
        tool_list_cache_ttl_seconds: How long (in seconds) to cache the tool
            list for a given JWT subject before re-fetching.
        retry_attempts: How many times to retry on 5xx / network errors in
            ``invoke``.  ``0`` means no retries (one attempt only).
    """

    _CACHE_SOFT_CAP = 1024

    def __init__(
        self,
        url: str,
        allowed_tools: frozenset[str] | list[str],
        *,
        request_timeout_seconds: float = 30.0,
        tool_list_cache_ttl_seconds: float = 60.0,
        retry_attempts: int = 2,
        mode: Literal["user", "admin"] = "user",
        admin_token: str | None = None,
    ) -> None:
        self.url = url
        self.allowed_tools = frozenset(allowed_tools)  # normalise to frozenset
        self.request_timeout_seconds = request_timeout_seconds
        self.tool_list_cache_ttl_seconds = tool_list_cache_ttl_seconds
        self.retry_attempts = retry_attempts
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = asyncio.Lock()
        self._mode = mode
        # admin_token is required for BOTH modes (MTRNIX-370 Phase 2a):
        # - admin-mode: X-Api-Token only
        # - user-mode:  X-Api-Token + X-ASOC-Session (per ASOC withAuth middleware §1.0)
        # An empty / None token is only allowed when the client is constructed without
        # a token (e.g. in tests or when admin_token is not yet configured). The actual
        # network calls will fail with McpAuthError if no token is set.
        if mode == "admin" and (not admin_token or not admin_token.strip()):
            raise ValueError(
                "admin_token is required when mode='admin' "
                "(it's the metatron-system-user token shared by both modes)"
            )
        self._admin_token: str | None = (
            admin_token if (admin_token and admin_token.strip()) else None
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> AsocMcpClient:
        """Construct in user mode from app settings.

        Uses the same admin_token as admin-mode — user-mode sends it as X-Api-Token
        alongside X-ASOC-Session (per ASOC withAuth middleware convention §1.0).
        admin_token may be empty if not yet configured; network calls will then fail
        with McpAuthError at runtime.
        """
        return cls(
            url=settings.asoc_mcp_url,
            allowed_tools=settings.asoc_mcp_allowed_tools,
            request_timeout_seconds=settings.asoc_mcp_request_timeout_seconds,
            tool_list_cache_ttl_seconds=settings.asoc_mcp_tool_list_cache_ttl_seconds,
            retry_attempts=settings.asoc_mcp_retry_attempts,
            mode="user",
            admin_token=settings.asoc_mcp_admin_token or None,
        )

    @classmethod
    def from_settings_admin(cls, settings: Settings) -> AsocMcpClient | None:
        """Construct in admin mode if settings.asoc_mcp_admin_token is set.

        Returns None if admin_token is empty (not configured). T1 sync should
        check for None and skip / log warning.
        """
        if not settings.asoc_mcp_admin_token:
            return None
        return cls(
            url=settings.asoc_mcp_url,
            allowed_tools=settings.asoc_mcp_allowed_tools,
            request_timeout_seconds=settings.asoc_mcp_request_timeout_seconds,
            tool_list_cache_ttl_seconds=settings.asoc_mcp_tool_list_cache_ttl_seconds,
            retry_attempts=settings.asoc_mcp_retry_attempts,
            mode="admin",
            admin_token=settings.asoc_mcp_admin_token,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_available_tools(self, session_id: str) -> list[AsocToolDescriptor]:
        """Return whitelisted tools available on the ASOC MCP server.

        Results are cached per session_id for ``tool_list_cache_ttl_seconds``.

        Args:
            session_id: The user's ASOC session ID (from X-ASOC-Session header).
                        Used as the cache key and forwarded in X-ASOC-Session header.

        Returns:
            Empty list when the MCP server is unreachable (graceful degradation).

        Raises:
            McpAuthError: session_id is empty, or ASOC returned 401/403.
        """
        if not session_id or not session_id.strip():
            raise McpAuthError("empty session_id")

        cache_key = self._cache_key(session_id)
        async with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry and time.monotonic() < entry.expires_at:
                logger.debug("asoc.mcp.tools_list.cache_hit", cache_key=cache_key)
                return entry.tools

        # Cache miss — fetch from MCP server.
        try:
            remote_tools = await self._fetch_tools_list(session_id)
        except McpAuthError:
            raise
        except (McpUnavailableError, OSError, ConnectionError) as exc:
            logger.warning("asoc.mcp.tools_list.unreachable", url=self.url, error=str(exc))
            return []
        except Exception as exc:
            logger.warning("asoc.mcp.tools_list.unexpected_error", url=self.url, error=str(exc))
            return []

        # Gate A: filter through whitelist.
        filtered = [t for t in remote_tools if t.name in self.allowed_tools]

        async with self._cache_lock:
            self._evict_if_needed()
            self._cache[cache_key] = _CacheEntry(
                tools=filtered,
                expires_at=time.monotonic() + self.tool_list_cache_ttl_seconds,
            )

        logger.info(
            "asoc.mcp.tools_list.fetched",
            url=self.url,
            total=len(remote_tools),
            whitelisted=len(filtered),
        )
        return filtered

    async def invoke(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsocToolCallResult:
        """Invoke a whitelisted tool on the ASOC MCP server.

        Args:
            session_id: The user's ASOC session ID, forwarded as X-ASOC-Session.
                        Pass an empty string only for admin-mode calls where
                        session context is not required (admin operates as
                        the predefined metatron system user with isadm role).
            tool_name: Name of the tool to call.
            arguments: Tool input parameters (JSON-serialisable dict).

        Returns:
            ``AsocToolCallResult`` with content blocks from the tool response.

        Raises:
            McpAuthError: session_id is empty (user-mode), or ASOC returned 401/403.
            ToolNotAllowedError: ``tool_name`` is not in ``allowed_tools``.
            McpUnavailableError: Server unreachable after all retry attempts.
            McpProtocolError: Malformed response or unexpected HTTP 4xx.
        """
        if self._mode == "user" and (not session_id or not session_id.strip()):
            raise McpAuthError("empty session_id")

        # Gate B: pre-dispatch whitelist check.
        self._check_whitelist(tool_name)

        return await self._call_with_retry(session_id, tool_name, arguments)

    async def health_check(self) -> bool:
        """Sanity-check the MCP endpoint (no user JWT needed).

        Returns:
            ``True`` if the server responds to a tools/list probe, ``False``
            otherwise.  Never raises.
        """
        if not self.url:
            return False
        try:
            await self._tools_list_unauthenticated_probe()
            return True
        except Exception as exc:
            logger.debug("asoc.mcp.health_check.failed", url=self.url, error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Whitelist helpers
    # ------------------------------------------------------------------

    def _check_whitelist(self, tool_name: str) -> None:
        if tool_name not in self.allowed_tools:
            raise ToolNotAllowedError(f"tool not in whitelist: {tool_name!r}")

    # ------------------------------------------------------------------
    # Auth header construction (per ASOC withAuth middleware §1.0)
    # ------------------------------------------------------------------

    def _auth_headers(self, session_id: str | None = None) -> dict[str, str]:
        """Return the auth headers for an outgoing MCP request.

        Admin mode: ``X-Api-Token`` only (no session context).
        User mode:  ``X-Api-Token`` + ``X-ASOC-Session`` (per ASOC withAuth §1.0).

        ASOC's ``withAuth`` middleware:
        1. If ``X-ASOC-Session`` present → checks ``X-Api-Token`` matches the
           metatron system-user token (constant-time compare) → 401 if not.
        2. If matches → ``VerifySession(session_id)`` resolves user → context
           built under user RBAC.
        3. No ``X-ASOC-Session`` → falls to existing user-API-token path →
           context built as ``metatron`` (admin).
        """
        headers: dict[str, str] = {}
        if self._admin_token:
            headers["X-Api-Token"] = self._admin_token
        if session_id is not None:
            headers["X-ASOC-Session"] = session_id
        return headers

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, session_id: str) -> str:
        """Build a stable cache key from session_id (already user-bound)."""
        return f"{self.url}|{session_id}"

    def _evict_if_needed(self) -> None:
        """Drop oldest 25 % of cache entries when the soft cap is exceeded.

        Must be called while holding ``_cache_lock``.
        """
        if len(self._cache) > self._CACHE_SOFT_CAP:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k].expires_at)
            drop_count = max(1, len(sorted_keys) // 4)
            for k in sorted_keys[:drop_count]:
                del self._cache[k]
            logger.debug(
                "asoc.mcp.cache.evicted",
                dropped=drop_count,
                remaining=len(self._cache),
            )

    # ------------------------------------------------------------------
    # MCP SDK wrappers (lazy imports)
    # ------------------------------------------------------------------

    async def _fetch_tools_list(self, session_id: str) -> list[AsocToolDescriptor]:
        """Open a streamable-HTTP session and call tools/list.

        Raises:
            McpAuthError: On 401/403 from the MCP server.
            McpUnavailableError: On network / 5xx errors.
            McpProtocolError: On malformed response.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = self._auth_headers(session_id if self._mode == "user" else None)
        try:
            async with streamablehttp_client(  # noqa: SIM117
                self.url,
                headers=headers,
                timeout=self.request_timeout_seconds,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
        except Exception as exc:
            raise self._map_exception(exc) from exc

        try:
            return [
                AsocToolDescriptor(
                    name=tool.name,
                    description=getattr(tool, "description", "") or "",
                    input_schema=dict(getattr(tool, "inputSchema", None) or {}),
                )
                for tool in result.tools
            ]
        except Exception as exc:
            raise McpProtocolError(f"failed to parse tools/list response: {exc}") from exc

    async def _call_with_retry(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsocToolCallResult:
        """Invoke a tool with retry on 5xx / network errors.

        Exponential backoff: 1 s, 2 s (up to ``retry_attempts``).
        Auth errors (McpAuthError) are never retried.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = self._auth_headers(session_id if self._mode == "user" else None)
        max_attempts = self.retry_attempts + 1  # retry_attempts=2 → 3 total attempts
        last_exc: Exception = McpUnavailableError("no attempts made")

        for attempt in range(max_attempts):
            try:
                async with streamablehttp_client(  # noqa: SIM117
                    self.url,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, arguments)

                # Parse content blocks.
                content: list[dict[str, Any]] = []
                for block in result.content:
                    content.append(
                        {
                            "type": getattr(block, "type", "text"),
                            "text": getattr(block, "text", str(block)),
                        }
                    )

                return AsocToolCallResult(
                    tool=tool_name,
                    content=content,
                    is_error=bool(getattr(result, "isError", False)),
                )

            except McpAuthError:
                # Never retry auth failures.
                raise
            except McpProtocolError:
                # Never retry protocol errors (4xx other than auth, malformed response).
                raise
            except (McpUnavailableError, OSError, ConnectionError) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    delay = 2.0**attempt  # 1 s, 2 s
                    logger.warning(
                        "asoc.mcp.invoke.retry",
                        tool=tool_name,
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                mapped = self._map_exception(exc)
                if isinstance(mapped, McpAuthError):
                    raise mapped from exc
                if isinstance(mapped, McpProtocolError):
                    raise mapped from exc
                last_exc = mapped
                if attempt < max_attempts - 1:
                    delay = 2.0**attempt
                    logger.warning(
                        "asoc.mcp.invoke.retry",
                        tool=tool_name,
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

        raise McpUnavailableError(
            f"asoc mcp invoke failed after {max_attempts} attempt(s): {last_exc}"
        )

    async def _tools_list_unauthenticated_probe(self) -> None:
        """Probe tools/list with no JWT — used only by health_check().

        We pass an empty Authorization header to avoid disclosing a real JWT
        in a health-check context.  ASOC may return 401, which we treat as
        "server is up" (it responded).
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(  # noqa: SIM117
            self.url,
            headers={},
            timeout=min(self.request_timeout_seconds, 5.0),
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.list_tools()

    # ------------------------------------------------------------------
    # Exception mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_exception(exc: Exception) -> AsocMcpError:
        """Map a raw exception from the MCP SDK or httpx into our hierarchy."""
        import httpx

        exc_str = str(exc).lower()

        # Auth errors.
        if "401" in exc_str or "unauthorized" in exc_str:
            return McpAuthError(f"ASOC MCP auth error (401): {exc}")
        if "403" in exc_str or "forbidden" in exc_str:
            return McpAuthError(f"ASOC MCP auth error (403): {exc}")

        # Protocol / 4xx errors (non-auth).
        if "4" in exc_str and any(
            c in exc_str for c in ["400", "404", "405", "408", "409", "422", "429"]
        ):
            return McpProtocolError(f"ASOC MCP protocol error: {exc}")

        # Network / 5xx → unavailable.
        if isinstance(
            exc, (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
        ):
            return McpUnavailableError(f"ASOC MCP unreachable: {exc}")
        if isinstance(exc, (OSError, ConnectionError, TimeoutError)):
            return McpUnavailableError(f"ASOC MCP unreachable: {exc}")
        if "5xx" in exc_str or "503" in exc_str or "502" in exc_str or "500" in exc_str:
            return McpUnavailableError(f"ASOC MCP server error: {exc}")

        # Default: treat unknown errors as protocol errors.
        return McpProtocolError(f"ASOC MCP unexpected error: {exc}")
