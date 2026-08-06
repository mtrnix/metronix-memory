"""Principal requirements for MCP agent-memory operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.mcp.principal import MCPPrincipal


async def test_personal_api_key_resolves_owner_as_mcp_principal() -> None:
    from metronix.mcp.auth import authenticate_http_request

    async def resolve_personal_key(token: str) -> MCPPrincipal | None:
        if token == "mtk_test":
            return MCPPrincipal("user-1", "editor", ("ws-a",), auth_method="personal_api_key")
        return None

    principal = await authenticate_http_request(
        "Bearer mtk_test",
        auth_enabled=False,
        secret_key="unused",
        principal_resolver=resolve_personal_key,
    )

    assert principal == MCPPrincipal("user-1", "editor", ("ws-a",), auth_method="personal_api_key")


async def test_shared_key_stays_without_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    from metronix.mcp.auth import authenticate_http_request

    monkeypatch.setenv("METRONIX_MCP_API_KEY", "shared-key")
    principal = await authenticate_http_request(
        "Bearer shared-key",
        auth_enabled=False,
        secret_key="unused",
        principal_resolver=None,
    )

    assert principal is None


async def test_personal_api_key_is_accepted_when_jwt_auth_is_enabled() -> None:
    from metronix.mcp.auth import authenticate_http_request

    async def resolve_personal_key(token: str) -> MCPPrincipal | None:
        return MCPPrincipal("user-1", "editor", ("ws-a",), auth_method="personal_api_key")

    principal = await authenticate_http_request(
        "Bearer mtk_test",
        auth_enabled=True,
        secret_key="unused",
        principal_resolver=resolve_personal_key,
    )

    assert principal is not None
    assert principal.auth_method == "personal_api_key"


@pytest.mark.asyncio
async def test_standalone_http_resolves_an_active_personal_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metronix.mcp import server

    api_key_store = MagicMock()
    api_key_store.resolve_key = AsyncMock(return_value={"source": "personal", "user_id": "u1"})
    user_store = MagicMock()
    user_store.get_user_by_id = AsyncMock(
        return_value={"id": "u1", "role": "editor", "workspace_ids": ["ws-a"], "is_active": True}
    )
    monkeypatch.setattr(
        server, "_get_standalone_personal_key_stores", lambda: (api_key_store, user_store)
    )

    principal = await server._resolve_standalone_mcp_personal_principal("mtk_test")

    assert principal == MCPPrincipal("u1", "editor", ("ws-a",), auth_method="personal_api_key")
