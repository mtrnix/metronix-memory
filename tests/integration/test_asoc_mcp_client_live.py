"""Integration tests for AsocMcpClient against a live ASOC MCP server.

Skip-gated: tests only run when ``METATRON_ASOC_MCP_INTEGRATION_TEST_URL`` is set.

Usage::

    METATRON_ASOC_MCP_INTEGRATION_TEST_URL=https://asoc-dev.example.com/mcp \\
    METATRON_ASOC_MCP_INTEGRATION_TEST_JWT=<valid-user-jwt> \\
    pytest tests/integration/test_asoc_mcp_client_live.py -v -m integration

Requires a valid ASOC user JWT that the target MCP server will accept.
"""

from __future__ import annotations

import os
import time

import jwt
import pytest

_INTEGRATION_URL = os.getenv("METATRON_ASOC_MCP_INTEGRATION_TEST_URL", "")
_INTEGRATION_JWT = os.getenv("METATRON_ASOC_MCP_INTEGRATION_TEST_JWT", "")

if not _INTEGRATION_URL:
    pytest.skip(
        "METATRON_ASOC_MCP_INTEGRATION_TEST_URL not set — skipping live ASOC MCP tests",
        allow_module_level=True,
    )

from metatron.core.asoc_constants import ASOC_MCP_READ_ONLY_TOOLS_DEFAULT  # noqa: E402
from metatron.integrations.asoc_mcp_client import (  # noqa: E402
    AsocMcpClient,
    ToolNotAllowedError,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_jwt(
    subject: str = "integration-test-user", secret: str = "test-secret-32-bytes!1234567890"
) -> str:
    """Generate a minimal test JWT for integration tests.

    NOTE: This JWT is NOT signed with the ASOC shared secret.  If the ASOC
    MCP server enforces signature verification, set ``METATRON_ASOC_MCP_INTEGRATION_TEST_JWT``
    to a real JWT instead and use ``_INTEGRATION_JWT``.
    """
    return jwt.encode(
        {"sub": subject, "iat": int(time.time()), "exp": int(time.time()) + 3600},
        secret,
        algorithm="HS256",
    )


def _get_test_jwt() -> str:
    """Return the integration JWT from env or a generated test token."""
    return _INTEGRATION_JWT or _make_test_jwt()


@pytest.fixture
def live_client() -> AsocMcpClient:
    return AsocMcpClient(
        url=_INTEGRATION_URL,
        allowed_tools=ASOC_MCP_READ_ONLY_TOOLS_DEFAULT,
        request_timeout_seconds=15.0,
        retry_attempts=1,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_live_tools_list_returns_at_least_one_whitelisted_tool(
    live_client: AsocMcpClient,
) -> None:
    """Live ASOC MCP server returns at least one tool from the default whitelist."""
    user_jwt = _get_test_jwt()
    tools = await live_client.list_available_tools(user_jwt)

    # Graceful degradation returns [] on unreachable — if the URL is set we expect
    # at least one tool to confirm the server is actually up.
    tool_names = {t.name for t in tools}
    whitelisted = tool_names & ASOC_MCP_READ_ONLY_TOOLS_DEFAULT
    assert len(whitelisted) >= 1, (
        f"No whitelisted tools returned from {_INTEGRATION_URL}. "
        f"Got: {tool_names}. Verify JWT is valid and server is accessible."
    )


async def test_live_invoke_safe_read_tool(live_client: AsocMcpClient) -> None:
    """Invoking a read-only tool (asoc_list_projects) succeeds without error."""
    user_jwt = _get_test_jwt()

    result = await live_client.invoke(user_jwt, "asoc_list_projects", {})

    assert result.tool == "asoc_list_projects"
    assert isinstance(result.content, list)


async def test_live_invoke_write_tool_blocked_pre_dispatch(live_client: AsocMcpClient) -> None:
    """Attempting to invoke a write tool raises ToolNotAllowedError without network call."""
    user_jwt = _get_test_jwt()

    with pytest.raises(ToolNotAllowedError):
        await live_client.invoke(user_jwt, "asoc_start_scan", {"project_id": "test"})


async def test_live_health_check_returns_true(live_client: AsocMcpClient) -> None:
    """health_check() returns True when the ASOC MCP server is reachable."""
    result = await live_client.health_check()
    assert result is True, (
        f"health_check() returned False for {_INTEGRATION_URL}. "
        "Verify the server is running and accessible."
    )
