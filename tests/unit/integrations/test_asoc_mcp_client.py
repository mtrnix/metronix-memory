"""Unit tests for AsocMcpClient (MTRNIX-370 Phase 2a).

The MCP SDK is mocked at the session boundary — ``_fetch_tools_list`` and
``_call_with_retry`` are patched via ``unittest.mock`` so no real MCP server is
contacted and the ``mcp`` package transport layer is never exercised.

Phase 2a changes (MTRNIX-370):
- User-mode now sends X-Api-Token + X-ASOC-Session (not Authorization: Bearer <jwt>).
- Both modes require admin_token (the shared metatron system-user token).
- list_available_tools / invoke accept session_id, not user_jwt.
- Cache is keyed on raw session_id (no JWT decoding).
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.core.asoc_constants import ASOC_MCP_READ_ONLY_TOOLS_DEFAULT
from metatron.integrations.asoc_mcp_client import (
    AsocMcpClient,
    AsocToolCallResult,
    AsocToolDescriptor,
    McpAuthError,
    McpProtocolError,
    McpUnavailableError,
    ToolNotAllowedError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_URL = "http://asoc-mcp.test/mcp"
_ADMIN_TOKEN = "admin-token-value"
_WRITE_TOOLS = {
    "asoc_start_scan",
    "asoc_update_issue",
    "asoc_delete_issue",
    "asoc_create_issue",
    "asoc_close_scan",
    "asoc_assign_issue",
    "asoc_reopen_issue",
    "asoc_update_layer",
    "asoc_delete_project",
    "asoc_create_project",
}


def _make_client(
    *,
    allowed_tools: frozenset[str] | list[str] = ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
    cache_ttl: float = 60.0,
    retry_attempts: int = 2,
    admin_token: str = _ADMIN_TOKEN,
) -> AsocMcpClient:
    """Create a user-mode client (with admin_token required)."""
    return AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=allowed_tools,
        tool_list_cache_ttl_seconds=cache_ttl,
        retry_attempts=retry_attempts,
        mode="user",
        admin_token=admin_token,
    )


def _make_descriptors(names: list[str]) -> list[AsocToolDescriptor]:
    return [
        AsocToolDescriptor(
            name=n,
            description=f"Description for {n}",
            input_schema={"type": "object", "properties": {}},
        )
        for n in names
    ]


# ---------------------------------------------------------------------------
# Test: whitelist constant
# ---------------------------------------------------------------------------


def test_default_whitelist_matches_confluence_spec() -> None:
    """Exactly 37 read-only tool names, verbatim from Confluence §3."""
    assert len(ASOC_MCP_READ_ONLY_TOOLS_DEFAULT) == 37

    expected = {
        "asoc_list_issues",
        "asoc_get_issue",
        "asoc_count_issues",
        "asoc_list_issue_statuses",
        "asoc_get_issue_available_transitions",
        "asoc_get_issue_comments",
        "asoc_get_issue_history",
        "asoc_get_issues_categories",
        "asoc_get_issues_filters",
        "asoc_list_projects",
        "asoc_get_project",
        "asoc_get_project_layer_tree",
        "asoc_list_layers",
        "asoc_get_layer",
        "asoc_list_scan_results",
        "asoc_get_scan_stats",
        "asoc_compare_scan_results",
        "asoc_list_security_checks",
        "asoc_get_security_check",
        "asoc_get_stats_all",
        "asoc_get_stats_severity",
        "asoc_get_stats_by_tool",
        "asoc_get_stats_projects",
        "asoc_get_integral_risk",
        "asoc_get_defect_time",
        "asoc_list_sboms",
        "asoc_list_dependencies",
        "asoc_get_dependency",
        "asoc_list_trackers",
        "asoc_get_tracker_task_types",
        "asoc_list_users",
        "asoc_list_groups",
        "asoc_get_current_user",
        "asoc_list_quality_gates",
        "asoc_get_layer_gates",
        "asoc_list_events",
        "asoc_get_copilot_fp_analysis",
    }
    assert expected == ASOC_MCP_READ_ONLY_TOOLS_DEFAULT


# ---------------------------------------------------------------------------
# Test: constructor
# ---------------------------------------------------------------------------


def test_init_normalises_allowed_tools_to_frozenset() -> None:
    client = AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=["asoc_list_issues", "asoc_get_issue"],
        mode="user",
        admin_token=_ADMIN_TOKEN,
    )
    assert isinstance(client.allowed_tools, frozenset)
    assert "asoc_list_issues" in client.allowed_tools


def test_init_admin_mode_requires_admin_token() -> None:
    """mode='admin' with admin_token=None raises ValueError."""
    with pytest.raises(ValueError, match="admin_token"):
        AsocMcpClient(
            url=_TEST_URL,
            allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
            mode="admin",
            admin_token=None,
        )


def test_init_admin_mode_requires_non_empty_admin_token() -> None:
    """mode='admin' with admin_token='' raises ValueError."""
    with pytest.raises(ValueError, match="admin_token"):
        AsocMcpClient(
            url=_TEST_URL,
            allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
            mode="admin",
            admin_token="",
        )


def test_init_admin_mode_with_token_succeeds() -> None:
    """mode='admin' with a real token succeeds and stores the token."""
    client = AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        mode="admin",
        admin_token="admin-token-value",
    )
    assert client._mode == "admin"
    assert client._admin_token == "admin-token-value"


def test_init_user_mode_with_token_succeeds() -> None:
    """mode='user' with admin_token succeeds (required for X-Api-Token header)."""
    client = AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        mode="user",
        admin_token=_ADMIN_TOKEN,
    )
    assert client._mode == "user"
    assert client._admin_token == _ADMIN_TOKEN


def test_init_user_mode_without_token_allowed() -> None:
    """mode='user' without token doesn't raise at init (fails at network call time)."""
    client = AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        mode="user",
        admin_token=None,
    )
    assert client._admin_token is None


# ---------------------------------------------------------------------------
# Test: auth headers — Phase 2a convention
# ---------------------------------------------------------------------------


def test_admin_mode_uses_only_x_api_token_header() -> None:
    """Admin-mode: X-Api-Token header only (no X-ASOC-Session)."""
    client = AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        mode="admin",
        admin_token="admin-token-value",
    )
    headers = client._auth_headers(session_id=None)
    assert "X-Api-Token" in headers
    assert headers["X-Api-Token"] == "admin-token-value"
    assert "X-ASOC-Session" not in headers
    assert "Authorization" not in headers


def test_user_mode_sends_both_x_api_token_and_x_asoc_session() -> None:
    """User-mode: both X-Api-Token and X-ASOC-Session headers (ASOC plan §1.0)."""
    client = _make_client()
    session_id = "test-session-id-abc"
    headers = client._auth_headers(session_id=session_id)
    assert "X-Api-Token" in headers
    assert headers["X-Api-Token"] == _ADMIN_TOKEN
    assert "X-ASOC-Session" in headers
    assert headers["X-ASOC-Session"] == session_id
    assert "Authorization" not in headers


def test_user_mode_without_session_id_omits_asoc_session_header() -> None:
    """Calling _auth_headers(session_id=None) omits X-ASOC-Session."""
    client = _make_client()
    headers = client._auth_headers(session_id=None)
    assert "X-Api-Token" in headers
    assert "X-ASOC-Session" not in headers


# ---------------------------------------------------------------------------
# Test: list_available_tools — happy path + filtering
# ---------------------------------------------------------------------------


async def test_list_available_tools_filters_to_whitelist() -> None:
    """Server returns 37 whitelisted + 10 write tools; only whitelisted are returned."""
    client = _make_client()
    all_names = list(ASOC_MCP_READ_ONLY_TOOLS_DEFAULT) + list(_WRITE_TOOLS)
    remote = _make_descriptors(all_names)

    with patch.object(client, "_fetch_tools_list", new=AsyncMock(return_value=remote)):
        result = await client.list_available_tools("session-123")

    assert len(result) == 37
    result_names = {t.name for t in result}
    assert result_names == ASOC_MCP_READ_ONLY_TOOLS_DEFAULT
    assert not result_names.intersection(_WRITE_TOOLS)


async def test_list_available_tools_forwards_session_id() -> None:
    """_fetch_tools_list receives the session_id."""
    client = _make_client()
    captured: list[str] = []

    async def fake_fetch(session_id: str) -> list[AsocToolDescriptor]:
        captured.append(session_id)
        return _make_descriptors(["asoc_list_issues"])

    with patch.object(client, "_fetch_tools_list", new=fake_fetch):
        session_id = "session-xyz-abc"
        await client.list_available_tools(session_id)

    assert len(captured) == 1
    assert captured[0] == session_id


# ---------------------------------------------------------------------------
# Test: list_available_tools — graceful degradation
# ---------------------------------------------------------------------------


async def test_list_available_tools_returns_empty_on_unreachable() -> None:
    """Network error → empty list (graceful degradation), no exception raised."""
    client = _make_client()

    with patch.object(
        client,
        "_fetch_tools_list",
        new=AsyncMock(side_effect=McpUnavailableError("connect refused")),
    ):
        result = await client.list_available_tools("session-123")

    assert result == []


# ---------------------------------------------------------------------------
# Test: list_available_tools — caching
# ---------------------------------------------------------------------------


async def test_list_available_tools_caches_with_ttl() -> None:
    """Two calls with the same session_id → _fetch_tools_list called only once."""
    client = _make_client(cache_ttl=60.0)
    fetch_mock = AsyncMock(return_value=_make_descriptors(["asoc_list_issues"]))

    with patch.object(client, "_fetch_tools_list", new=fetch_mock):
        await client.list_available_tools("session-same")
        await client.list_available_tools("session-same")

    assert fetch_mock.call_count == 1


async def test_list_available_tools_cache_invalidates_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After TTL expires the cache misses and _fetch_tools_list is called again."""
    client = _make_client(cache_ttl=10.0)
    fetch_mock = AsyncMock(return_value=_make_descriptors(["asoc_list_issues"]))
    session_id = "session-ttl-user"

    tick = 0.0

    def fake_monotonic() -> float:
        return tick

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    with patch.object(client, "_fetch_tools_list", new=fetch_mock):
        await client.list_available_tools(session_id)
        assert fetch_mock.call_count == 1

        # Advance time past TTL.
        tick = 11.0
        await client.list_available_tools(session_id)
        assert fetch_mock.call_count == 2


async def test_list_available_tools_cache_per_session_id() -> None:
    """Different session_ids → separate cache entries, fetch called twice."""
    client = _make_client(cache_ttl=60.0)
    fetch_mock = AsyncMock(return_value=_make_descriptors(["asoc_list_issues"]))

    session1 = "session-alice"
    session2 = "session-bob"

    with patch.object(client, "_fetch_tools_list", new=fetch_mock):
        await client.list_available_tools(session1)
        await client.list_available_tools(session2)

    assert fetch_mock.call_count == 2


async def test_list_available_tools_cache_evicts_under_pressure() -> None:
    """When the cache exceeds the soft cap, oldest entries are evicted."""
    client = _make_client(cache_ttl=3600.0)
    # Overflow the 1024-entry soft cap.
    overflow_count = 1100

    # Seed the cache directly to avoid real network calls.
    for i in range(overflow_count):
        cache_key = f"{_TEST_URL}|session-{i}"
        from metatron.integrations.asoc_mcp_client import _CacheEntry

        client._cache[cache_key] = _CacheEntry(
            tools=[],
            expires_at=time.monotonic() + float(i),  # older entries have smaller expires_at
        )

    # Trigger eviction via a new list_available_tools call that misses cache.
    fetch_mock = AsyncMock(return_value=[])
    with patch.object(client, "_fetch_tools_list", new=fetch_mock):
        await client.list_available_tools("evict-test-session")

    # After eviction, cache size should be well below 1100.
    assert len(client._cache) <= client._CACHE_SOFT_CAP + 2  # +1 for the new entry


async def test_list_available_tools_empty_session_id_raises() -> None:
    """Empty session_id raises McpAuthError immediately without any network call."""
    client = _make_client()
    fetch_mock = AsyncMock(return_value=[])

    with patch.object(client, "_fetch_tools_list", new=fetch_mock), pytest.raises(McpAuthError):
        await client.list_available_tools("")

    fetch_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Test: invoke — happy path
# ---------------------------------------------------------------------------


async def test_invoke_happy_path() -> None:
    """Successful invoke returns a populated AsocToolCallResult."""
    client = _make_client()
    tool_name = "asoc_list_issues"
    arguments = {"project_id": "proj-1"}
    expected_content = [{"type": "text", "text": "issue list here"}]
    expected_result = AsocToolCallResult(
        tool=tool_name,
        content=expected_content,
        is_error=False,
    )

    with patch.object(
        client,
        "_call_with_retry",
        new=AsyncMock(return_value=expected_result),
    ):
        result = await client.invoke("session-123", tool_name, arguments)

    assert result.tool == tool_name
    assert result.content == expected_content
    assert not result.is_error


# ---------------------------------------------------------------------------
# Test: invoke — double-gate whitelist
# ---------------------------------------------------------------------------


async def test_invoke_pre_dispatch_double_gate_rejects_write_tool() -> None:
    """A write tool is rejected by gate B BEFORE any network call is made."""
    client = _make_client()
    retry_mock = AsyncMock()

    with (
        patch.object(client, "_call_with_retry", new=retry_mock),
        pytest.raises(ToolNotAllowedError),
    ):
        await client.invoke("session-123", "asoc_start_scan", {})

    retry_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Test: invoke — session_id forwarding
# ---------------------------------------------------------------------------


async def test_invoke_forwards_session_id_to_retry() -> None:
    """The session_id passed to invoke is forwarded to _call_with_retry."""
    client = _make_client()
    captured_session: list[str] = []

    async def fake_retry(
        session_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> AsocToolCallResult:
        captured_session.append(session_id)
        return AsocToolCallResult(tool=tool_name, content=[], is_error=False)

    with patch.object(client, "_call_with_retry", new=fake_retry):
        session_id = "forward-test-session"
        await client.invoke(session_id, "asoc_list_issues", {})

    assert len(captured_session) == 1
    assert captured_session[0] == session_id


# ---------------------------------------------------------------------------
# Test: invoke — auth errors
# ---------------------------------------------------------------------------


async def test_invoke_raises_mcp_auth_error_on_401() -> None:
    client = _make_client()
    with (
        patch.object(
            client,
            "_call_with_retry",
            new=AsyncMock(side_effect=McpAuthError("401 unauthorized")),
        ),
        pytest.raises(McpAuthError),
    ):
        await client.invoke("session-123", "asoc_list_issues", {})


async def test_invoke_raises_mcp_auth_error_on_403() -> None:
    client = _make_client()
    with (
        patch.object(
            client,
            "_call_with_retry",
            new=AsyncMock(side_effect=McpAuthError("403 forbidden")),
        ),
        pytest.raises(McpAuthError),
    ):
        await client.invoke("session-123", "asoc_list_issues", {})


# ---------------------------------------------------------------------------
# Test: invoke — network errors
# ---------------------------------------------------------------------------


async def test_invoke_raises_mcp_unavailable_on_connect_refused() -> None:
    client = _make_client()
    with (
        patch.object(
            client,
            "_call_with_retry",
            new=AsyncMock(side_effect=McpUnavailableError("connect refused")),
        ),
        pytest.raises(McpUnavailableError),
    ):
        await client.invoke("session-123", "asoc_list_issues", {})


# ---------------------------------------------------------------------------
# Test: invoke — retry logic
# ---------------------------------------------------------------------------


async def test_invoke_retries_on_5xx_then_succeeds() -> None:
    """invoke retries on 5xx — tested by wiring _call_with_retry to fail once then succeed."""
    client = _make_client(retry_attempts=2)
    tool_name = "asoc_list_issues"
    success_result = AsocToolCallResult(tool=tool_name, content=[], is_error=False)

    call_count = 0

    async def fail_once_then_succeed(
        session_id: str, tool_name_arg: str, arguments: dict[str, Any]
    ) -> AsocToolCallResult:
        nonlocal call_count
        call_count += 1
        return success_result

    with patch.object(client, "_call_with_retry", new=fail_once_then_succeed):
        result = await client.invoke("session-123", tool_name, {})

    assert result.tool == tool_name
    assert call_count == 1

    # Also verify the actual _call_with_retry retry loop by patching at the SDK module level.
    client2 = _make_client(retry_attempts=2)
    sdk_call_count = 0

    from mcp.types import CallToolResult

    mock_result = MagicMock(spec=CallToolResult)
    mock_result.content = []
    mock_result.isError = False

    async def mock_session_call_tool(
        name: str, arguments: dict[str, Any] | None = None, **kwargs: Any
    ) -> Any:
        nonlocal sdk_call_count
        sdk_call_count += 1
        if sdk_call_count < 2:
            raise ConnectionError("503 service unavailable")
        return mock_result

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.call_tool = mock_session_call_tool
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_transport_ctx = MagicMock()
    mock_transport_ctx.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock(), None))
    mock_transport_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("mcp.client.streamable_http.streamablehttp_client", return_value=mock_transport_ctx),
        patch("mcp.ClientSession", return_value=mock_session),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        result2 = await client2._call_with_retry("session-123", tool_name, {})

    assert result2.tool == tool_name
    assert sdk_call_count == 2  # first call failed, second succeeded


async def test_invoke_raises_mcp_unavailable_after_retry_exhaustion() -> None:
    """All retry attempts fail → McpUnavailableError raised."""
    client = _make_client(retry_attempts=2)
    with (
        patch.object(
            client,
            "_call_with_retry",
            new=AsyncMock(side_effect=McpUnavailableError("exhausted")),
        ),
        pytest.raises(McpUnavailableError),
    ):
        await client.invoke("session-123", "asoc_list_issues", {})


async def test_invoke_raises_mcp_protocol_error_on_malformed_response() -> None:
    client = _make_client()
    with (
        patch.object(
            client,
            "_call_with_retry",
            new=AsyncMock(side_effect=McpProtocolError("malformed JSON-RPC response")),
        ),
        pytest.raises(McpProtocolError),
    ):
        await client.invoke("session-123", "asoc_list_issues", {})


async def test_invoke_raises_mcp_protocol_error_on_4xx_other_than_auth() -> None:
    """429 / 422 / 400 → McpProtocolError (not auth, not unavailable)."""
    client = _make_client()
    with (
        patch.object(
            client,
            "_call_with_retry",
            new=AsyncMock(side_effect=McpProtocolError("429 rate limited")),
        ),
        pytest.raises(McpProtocolError),
    ):
        await client.invoke("session-123", "asoc_list_issues", {})


async def test_invoke_does_not_retry_on_auth_errors() -> None:
    """On 401, _call_with_retry is called exactly once (no retry), McpAuthError raised."""
    client = _make_client(retry_attempts=2)
    call_count = 0

    async def fail_auth(
        session_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> AsocToolCallResult:
        nonlocal call_count
        call_count += 1
        raise McpAuthError("401 unauthorized")

    with patch.object(client, "_call_with_retry", new=fail_auth), pytest.raises(McpAuthError):
        await client.invoke("session-123", "asoc_list_issues", {})

    assert call_count == 1  # invoke calls _call_with_retry exactly once


async def test_invoke_empty_session_id_raises_in_user_mode() -> None:
    """Empty session_id raises McpAuthError in user-mode, no _call_with_retry invoked."""
    client = _make_client()
    retry_mock = AsyncMock()
    with patch.object(client, "_call_with_retry", new=retry_mock), pytest.raises(McpAuthError):
        await client.invoke("", "asoc_list_issues", {})
    retry_mock.assert_not_called()


async def test_invoke_empty_session_id_allowed_in_admin_mode() -> None:
    """Admin-mode calls don't require a session_id (acts as metatron system user)."""
    client = AsocMcpClient(
        url=_TEST_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        mode="admin",
        admin_token=_ADMIN_TOKEN,
    )
    expected_result = AsocToolCallResult(tool="asoc_list_issues", content=[], is_error=False)
    with patch.object(client, "_call_with_retry", new=AsyncMock(return_value=expected_result)):
        result = await client.invoke("", "asoc_list_issues", {})
    assert result.tool == "asoc_list_issues"


# ---------------------------------------------------------------------------
# Test: health_check
# ---------------------------------------------------------------------------


async def test_health_check_returns_true_on_reachable() -> None:
    client = _make_client()
    with patch.object(
        client,
        "_tools_list_unauthenticated_probe",
        new=AsyncMock(return_value=None),
    ):
        assert await client.health_check() is True


async def test_health_check_returns_false_on_unreachable() -> None:
    client = _make_client()
    with patch.object(
        client,
        "_tools_list_unauthenticated_probe",
        new=AsyncMock(side_effect=ConnectionError("refused")),
    ):
        assert await client.health_check() is False


async def test_health_check_returns_false_when_url_empty() -> None:
    client = AsocMcpClient(url="", allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT)
    assert await client.health_check() is False


# ---------------------------------------------------------------------------
# Test: Settings validator for asoc_mcp_allowed_tools
# ---------------------------------------------------------------------------


def test_settings_validator_rejects_non_asoc_tool_names() -> None:
    """Settings raises ValueError when tool names don't start with 'asoc_'."""
    from pydantic import ValidationError

    from metatron.core.config import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            METATRON_ASOC_MCP_ALLOWED_TOOLS=["asoc_list_issues", "not_asoc_tool"],
            METATRON_ENV="development",
        )
    assert "asoc_" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test: from_settings classmethods
# ---------------------------------------------------------------------------


def test_from_settings_admin_returns_none_when_token_empty() -> None:
    """from_settings_admin() returns None when asoc_mcp_admin_token is empty."""
    from metatron.core.config import Settings
    from metatron.integrations.asoc_mcp_client import AsocMcpClient

    settings = Settings.model_construct(asoc_mcp_admin_token="")
    result = AsocMcpClient.from_settings_admin(settings)
    assert result is None


def test_from_settings_admin_returns_client_when_token_set() -> None:
    """from_settings_admin() returns configured admin-mode AsocMcpClient when token set."""
    from metatron.core.config import Settings
    from metatron.integrations.asoc_mcp_client import AsocMcpClient

    settings = Settings.model_construct(asoc_mcp_admin_token="my-admin-token")
    client = AsocMcpClient.from_settings_admin(settings)
    assert client is not None
    assert client._mode == "admin"
    assert client._admin_token == "my-admin-token"


def test_from_settings_user_mode_includes_admin_token() -> None:
    """from_settings() populates admin_token for user-mode (needed for X-Api-Token header)."""
    from metatron.core.config import Settings
    from metatron.integrations.asoc_mcp_client import AsocMcpClient

    settings = Settings.model_construct(
        asoc_mcp_url="http://asoc/mcp",
        asoc_mcp_admin_token="shared-token",
        asoc_mcp_allowed_tools=list(ASOC_MCP_READ_ONLY_TOOLS_DEFAULT),
        asoc_mcp_tool_list_cache_ttl_seconds=60.0,
        asoc_mcp_request_timeout_seconds=30.0,
        asoc_mcp_retry_attempts=2,
    )
    client = AsocMcpClient.from_settings(settings)
    assert client._mode == "user"
    assert client._admin_token == "shared-token"
