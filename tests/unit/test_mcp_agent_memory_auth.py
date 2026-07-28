"""Principal requirements for MCP agent-memory operations."""

from __future__ import annotations

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

    assert principal == MCPPrincipal(
        "user-1", "editor", ("ws-a",), auth_method="personal_api_key"
    )


async def test_shared_key_stays_without_principal() -> None:
    from metronix.mcp.auth import authenticate_http_request

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
