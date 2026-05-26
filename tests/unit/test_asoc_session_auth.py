"""Unit tests for AsocSessionAuth and asoc_chat_auth (MTRNIX-370 Phase 2a).

Tests the session-based auth module that replaces the JWT-based asoc_jwt.py:
- AsocAuthContext dataclass shape
- AsocSessionAuth: cache hit / miss / eviction / TTL invalidation
- _fetch_context: happy path, auth error, unavailable, malformed response
- asoc_chat_auth FastAPI dependency: missing header, not configured, valid session
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from metatron.auth.asoc_session import (
    AsocAuthContext,
    AsocSessionAuth,
    _extract_json_from_content,
    asoc_admin_auth,
    asoc_chat_auth,
)
from metatron.integrations.asoc_mcp_client import (
    AsocMcpClient,
    AsocToolCallResult,
    McpAuthError,
    McpUnavailableError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = "test-admin-token"
_TEST_MCP_URL = "http://asoc-mcp.test/mcp"


def _make_mcp_client() -> AsocMcpClient:
    from metatron.core.asoc_constants import ASOC_MCP_READ_ONLY_TOOLS_DEFAULT

    return AsocMcpClient(
        url=_TEST_MCP_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        mode="user",
        admin_token=_ADMIN_TOKEN,
    )


def _make_session_auth(ttl: float = 3600.0) -> AsocSessionAuth:
    return AsocSessionAuth(mcp_client=_make_mcp_client(), ttl_seconds=ttl)


def _make_auth_context(session_id: str = "session-abc") -> AsocAuthContext:
    return AsocAuthContext(
        session_id=session_id,
        user_id="user-123",
        username="alice",
        display_name="Alice Tester",
        email="alice@example.com",
        roles=["viewer", "editor"],
    )


def _make_get_current_user_result(user_id: str = "user-123") -> AsocToolCallResult:
    """Simulated asoc_get_current_user response."""
    payload = {
        "id": user_id,
        "username": "alice",
        "display_name": "Alice Tester",
        "email": "alice@example.com",
        "roles": ["viewer", "editor"],
        "session_id": "session-abc",
    }
    import json

    return AsocToolCallResult(
        tool="asoc_get_current_user",
        content=[{"type": "text", "text": json.dumps(payload)}],
        is_error=False,
    )


# ---------------------------------------------------------------------------
# Test: AsocAuthContext shape
# ---------------------------------------------------------------------------


def test_auth_context_is_frozen() -> None:
    ctx = _make_auth_context()
    with pytest.raises((AttributeError, TypeError)):
        ctx.user_id = "modified"  # type: ignore[misc]


def test_auth_context_fields() -> None:
    ctx = AsocAuthContext(
        session_id="s1",
        user_id="u1",
        username="bob",
        display_name="Bob",
        email="bob@example.com",
        roles=["admin"],
    )
    assert ctx.session_id == "s1"
    assert ctx.user_id == "u1"
    assert ctx.username == "bob"
    assert ctx.display_name == "Bob"
    assert ctx.email == "bob@example.com"
    assert ctx.roles == ["admin"]


# ---------------------------------------------------------------------------
# Test: _extract_json_from_content helper
# ---------------------------------------------------------------------------


def test_extract_json_from_text_block() -> None:
    import json

    payload = {"id": "u1", "username": "alice"}
    content = [{"type": "text", "text": json.dumps(payload)}]
    assert _extract_json_from_content(content) == payload


def test_extract_json_from_json_block() -> None:
    payload = {"id": "u1", "username": "alice"}
    content = [{"type": "json", "data": payload}]
    assert _extract_json_from_content(content) == payload


def test_extract_json_skips_non_json_text_then_finds_json() -> None:
    import json

    payload = {"id": "u2"}
    content = [
        {"type": "text", "text": "not json"},
        {"type": "text", "text": json.dumps(payload)},
    ]
    assert _extract_json_from_content(content) == payload


def test_extract_json_raises_on_no_parseable_block() -> None:
    content = [{"type": "text", "text": "plain text, not json"}]
    with pytest.raises(ValueError, match="no parseable JSON"):
        _extract_json_from_content(content)


def test_extract_json_raises_on_empty_content() -> None:
    with pytest.raises(ValueError, match="no parseable JSON"):
        _extract_json_from_content([])


# ---------------------------------------------------------------------------
# Test: AsocSessionAuth.validate — cache hit
# ---------------------------------------------------------------------------


async def test_validate_cache_hit_returns_cached_context() -> None:
    """Second call with the same session_id returns cached context."""
    auth = _make_session_auth(ttl=3600.0)
    ctx = _make_auth_context("session-xyz")

    # Pre-populate the cache directly.
    from metatron.auth.asoc_session import _CacheEntry

    auth._cache["session-xyz"] = _CacheEntry(
        context=ctx,
        expires_at=time.monotonic() + 3600.0,
    )

    # Validate should return the cached entry without calling MCP.
    with patch.object(auth, "_fetch_context", new=AsyncMock()) as mock_fetch:
        result = await auth.validate("session-xyz")

    assert result is ctx
    mock_fetch.assert_not_called()


async def test_validate_cache_miss_calls_fetch_context() -> None:
    """Cache miss triggers _fetch_context and caches the result."""
    auth = _make_session_auth(ttl=3600.0)
    expected_ctx = _make_auth_context("session-new")

    with patch.object(auth, "_fetch_context", new=AsyncMock(return_value=expected_ctx)):
        result = await auth.validate("session-new")

    assert result == expected_ctx
    # Result should now be cached.
    assert "session-new" in auth._cache


async def test_validate_expired_cache_entry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expired cache entries are refetched."""
    auth = _make_session_auth(ttl=10.0)
    old_ctx = _make_auth_context("session-ttl")
    new_ctx = AsocAuthContext(
        session_id="session-ttl",
        user_id="user-456",
        username="bob",
        display_name="Bob",
        email="bob@example.com",
        roles=["viewer"],
    )

    tick = 0.0

    def fake_monotonic() -> float:
        return tick

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    from metatron.auth.asoc_session import _CacheEntry

    auth._cache["session-ttl"] = _CacheEntry(context=old_ctx, expires_at=5.0)

    # Advance past TTL.
    tick = 11.0

    with patch.object(auth, "_fetch_context", new=AsyncMock(return_value=new_ctx)):
        result = await auth.validate("session-ttl")

    assert result == new_ctx


async def test_validate_empty_session_id_raises_401() -> None:
    """Empty session_id raises HTTPException 401 immediately."""
    from fastapi import HTTPException

    auth = _make_session_auth()
    with pytest.raises(HTTPException) as exc_info:
        await auth.validate("")
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Test: AsocSessionAuth._fetch_context — happy path
# ---------------------------------------------------------------------------


async def test_fetch_context_parses_get_current_user_response() -> None:
    """Happy path: asoc_get_current_user returns valid payload."""
    auth = _make_session_auth()
    result_mock = _make_get_current_user_result(user_id="user-789")

    with patch.object(auth._mcp_client, "invoke", new=AsyncMock(return_value=result_mock)):
        ctx = await auth._fetch_context("session-abc")

    assert ctx.session_id == "session-abc"
    assert ctx.user_id == "user-789"
    assert ctx.username == "alice"
    assert ctx.email == "alice@example.com"
    assert "viewer" in ctx.roles


# ---------------------------------------------------------------------------
# Test: AsocSessionAuth._fetch_context — error paths
# ---------------------------------------------------------------------------


async def test_fetch_context_mcp_auth_error_raises_401() -> None:
    """McpAuthError from invoke → HTTPException 401."""
    from fastapi import HTTPException

    auth = _make_session_auth()
    with (
        patch.object(auth._mcp_client, "invoke", new=AsyncMock(side_effect=McpAuthError("401"))),
        pytest.raises(HTTPException) as exc_info,
    ):
        await auth._fetch_context("bad-session")
    assert exc_info.value.status_code == 401


async def test_fetch_context_mcp_unavailable_raises_502() -> None:
    """McpUnavailableError from invoke → HTTPException 502."""
    from fastapi import HTTPException

    auth = _make_session_auth()
    with (
        patch.object(
            auth._mcp_client,
            "invoke",
            new=AsyncMock(side_effect=McpUnavailableError("timeout")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await auth._fetch_context("session-abc")
    assert exc_info.value.status_code == 502


async def test_fetch_context_malformed_response_raises_502() -> None:
    """Response without 'id' field → HTTPException 502."""
    import json

    from fastapi import HTTPException

    auth = _make_session_auth()
    bad_result = AsocToolCallResult(
        tool="asoc_get_current_user",
        content=[{"type": "text", "text": json.dumps({"no_id_here": True})}],
        is_error=False,
    )
    with (
        patch.object(auth._mcp_client, "invoke", new=AsyncMock(return_value=bad_result)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await auth._fetch_context("session-abc")
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# Test: AsocSessionAuth cache eviction
# ---------------------------------------------------------------------------


async def test_cache_evicts_when_soft_cap_exceeded() -> None:
    """Cache evicts oldest 25 % when it grows beyond the soft cap."""
    auth = _make_session_auth(ttl=3600.0)

    from metatron.auth.asoc_session import _CacheEntry

    overflow_count = auth._CACHE_SOFT_CAP + 100
    for i in range(overflow_count):
        sid = f"session-{i}"
        ctx = _make_auth_context(sid)
        auth._cache[sid] = _CacheEntry(context=ctx, expires_at=time.monotonic() + float(i))

    # Trigger eviction by calling validate which will hit _fetch_context on a new session.
    new_ctx = _make_auth_context("evict-trigger-session")
    with patch.object(auth, "_fetch_context", new=AsyncMock(return_value=new_ctx)):
        await auth.validate("evict-trigger-session")

    # Cache should be well below the pre-eviction peak.
    assert len(auth._cache) <= auth._CACHE_SOFT_CAP + 2


# ---------------------------------------------------------------------------
# Test: AsocSessionAuth.invalidate
# ---------------------------------------------------------------------------


def test_invalidate_removes_cached_entry() -> None:
    from metatron.auth.asoc_session import _CacheEntry

    auth = _make_session_auth()
    ctx = _make_auth_context("session-to-remove")
    auth._cache["session-to-remove"] = _CacheEntry(
        context=ctx, expires_at=time.monotonic() + 3600.0
    )
    assert "session-to-remove" in auth._cache
    auth.invalidate("session-to-remove")
    assert "session-to-remove" not in auth._cache


def test_invalidate_noop_on_missing_entry() -> None:
    auth = _make_session_auth()
    auth.invalidate("no-such-session")  # must not raise


# ---------------------------------------------------------------------------
# Test: asoc_chat_auth FastAPI dependency
# ---------------------------------------------------------------------------


def _make_test_app(session_auth: AsocSessionAuth | None) -> FastAPI:
    """Build a minimal FastAPI app with asoc_chat_auth wired."""
    app = FastAPI()
    app.state.asoc_session_auth = session_auth

    @app.get("/test-auth")
    async def test_endpoint(request: Request) -> dict[str, str]:
        ctx = await asoc_chat_auth(request)
        return {"user_id": ctx.user_id, "session_id": ctx.session_id}

    return app


def test_asoc_chat_auth_missing_header_returns_401() -> None:
    auth = _make_session_auth()
    app = _make_test_app(auth)
    client = TestClient(app, raise_server_exceptions=False)
    # No X-ASOC-Session header.
    resp = client.get("/test-auth")
    assert resp.status_code == 401


def test_asoc_chat_auth_not_configured_returns_503() -> None:
    app = _make_test_app(None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/test-auth", headers={"X-ASOC-Session": "some-session"})
    assert resp.status_code == 503


async def test_asoc_chat_auth_valid_session_returns_context() -> None:
    """Valid session → asoc_chat_auth returns the context."""

    session_id = "session-valid"
    expected_ctx = _make_auth_context(session_id)
    auth = _make_session_auth()

    with patch.object(auth, "validate", new=AsyncMock(return_value=expected_ctx)):
        # Build a fake request.
        app = FastAPI()
        app.state.asoc_session_auth = auth
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"x-asoc-session", session_id.encode())],
            "query_string": b"",
            "app": app,
        }
        request = Request(scope)
        ctx = await asoc_chat_auth(request)

    assert ctx.user_id == expected_ctx.user_id
    assert ctx.session_id == session_id


async def test_asoc_chat_auth_invalid_session_propagates_401() -> None:
    """If validate() raises 401, asoc_chat_auth propagates it."""
    from fastapi import HTTPException

    auth = _make_session_auth()

    with patch.object(
        auth,
        "validate",
        new=AsyncMock(side_effect=HTTPException(status_code=401, detail="invalid")),
    ):
        app = FastAPI()
        app.state.asoc_session_auth = auth
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"x-asoc-session", b"bad-session")],
            "query_string": b"",
            "app": app,
        }
        request = Request(scope)
        with pytest.raises(HTTPException) as exc_info:
            await asoc_chat_auth(request)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Test: asoc_admin_auth FastAPI dependency
# ---------------------------------------------------------------------------

_ADMIN_TOKEN_VALUE = "super-secret-admin-token"


def _make_admin_settings(token: str = _ADMIN_TOKEN_VALUE) -> object:
    """Minimal settings stub with asoc_mcp_admin_token."""

    class _Settings:
        asoc_mcp_admin_token = token

    return _Settings()


async def _make_admin_request(
    auth_header: str | None,
    admin_token: str = _ADMIN_TOKEN_VALUE,
) -> Request:
    app = FastAPI()
    app.state.settings = _make_admin_settings(admin_token)
    headers: list[tuple[bytes, bytes]] = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode()))
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": "/test-admin",
        "headers": headers,
        "query_string": b"",
        "app": app,
    }
    return Request(scope)


async def test_asoc_admin_auth_valid_token_returns_none() -> None:
    """Correct Bearer token → returns None (no user context for admin)."""
    request = await _make_admin_request(f"Bearer {_ADMIN_TOKEN_VALUE}")
    result = await asoc_admin_auth(request)
    assert result is None


async def test_asoc_admin_auth_missing_header_returns_401() -> None:
    """No Authorization header → 401."""
    from fastapi import HTTPException

    request = await _make_admin_request(None)
    with pytest.raises(HTTPException) as exc_info:
        await asoc_admin_auth(request)
    assert exc_info.value.status_code == 401


async def test_asoc_admin_auth_wrong_token_returns_401() -> None:
    """Wrong Bearer token → 401."""
    from fastapi import HTTPException

    request = await _make_admin_request("Bearer wrong-token")
    with pytest.raises(HTTPException) as exc_info:
        await asoc_admin_auth(request)
    assert exc_info.value.status_code == 401


async def test_asoc_admin_auth_not_bearer_returns_401() -> None:
    """Non-Bearer auth scheme → 401."""
    from fastapi import HTTPException

    request = await _make_admin_request("Basic dXNlcjpwYXNz")
    with pytest.raises(HTTPException) as exc_info:
        await asoc_admin_auth(request)
    assert exc_info.value.status_code == 401


async def test_asoc_admin_auth_token_not_configured_returns_503() -> None:
    """Empty admin token → 503 fail-closed."""
    from fastapi import HTTPException

    request = await _make_admin_request(f"Bearer {_ADMIN_TOKEN_VALUE}", admin_token="")
    with pytest.raises(HTTPException) as exc_info:
        await asoc_admin_auth(request)
    assert exc_info.value.status_code == 503


async def test_asoc_admin_auth_constant_time_compare() -> None:
    """Verify constant-time comparison is used (no short-circuit on first byte)."""
    import secrets as _secrets
    from unittest.mock import patch as _patch

    request = await _make_admin_request(f"Bearer {_ADMIN_TOKEN_VALUE}")
    compare_calls: list[tuple[str, str]] = []

    original_compare = _secrets.compare_digest

    def spy_compare(a: str, b: str) -> bool:
        compare_calls.append((a, b))
        return original_compare(a, b)

    with _patch("metatron.auth.asoc_session.secrets.compare_digest", side_effect=spy_compare):
        await asoc_admin_auth(request)

    assert len(compare_calls) == 1
    assert compare_calls[0][0] == _ADMIN_TOKEN_VALUE  # provided
    assert compare_calls[0][1] == _ADMIN_TOKEN_VALUE  # expected
