"""MCP agent-memory authorization boundary tests."""

from unittest.mock import AsyncMock, patch

import pytest

from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal


@pytest.mark.asyncio
async def test_missing_principal_is_denied_before_authorizer_store_access():
    from metronix.mcp.tools._agent_access import require_agent_access

    with pytest.raises(PermissionError, match="unauthorized agent memory access"):
        await require_agent_access("ws-a", "agent-a", "read")


@pytest.mark.asyncio
async def test_guard_builds_mcp_memory_request_for_shared_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metronix.auth.policy import AuthorizationDecision, ResourceType, Transport
    from metronix.mcp.tools import _agent_access

    class DenyingEvaluator:
        request = None

        async def authorize(self, request):
            self.request = request
            return AuthorizationDecision("decision", False, "no_active_grant")

    evaluator = DenyingEvaluator()
    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: evaluator)
    token = bind_principal(MCPPrincipal("u1", "editor", ("ws-a",)))
    try:
        with pytest.raises(PermissionError, match="unauthorized agent memory access"):
            await _agent_access.require_agent_access("ws-a", "agent-a", "read")
    finally:
        reset_principal(token)

    assert evaluator.request.resource_type is ResourceType.MEMORY
    assert evaluator.request.transport is Transport.MCP
    assert evaluator.request.agent_id == "agent-a"


@pytest.mark.asyncio
async def test_denied_update_does_not_query_memory_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metronix.auth.policy import AuthorizationDecision
    from metronix.mcp.tools import _agent_access
    from metronix.mcp.tools.memory_update import metronix_memory_update

    class DenyingEvaluator:
        async def authorize(self, *args: object) -> AuthorizationDecision:
            return AuthorizationDecision("decision", False, "no_active_grant")

    service = AsyncMock()
    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: DenyingEvaluator())
    token = bind_principal(MCPPrincipal("u1", "editor", ("ws-a",)))
    try:
        with patch(
            "metronix.mcp.tools.memory_update._memory_deps.build_memory_service_for_workspace",
            new=AsyncMock(return_value=service),
        ) as build_service:
            out = await metronix_memory_update(
                record_id="foreign-record",
                agent_id="other-agent",
                workspace_id="ws-a",
                content="attempted change",
            )
    finally:
        reset_principal(token)

    assert out["error"]["code"] == "AUTH_REQUIRED"
    build_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_principal_search_does_not_query_memory_service() -> None:
    from metronix.mcp.tools.memory_search import metronix_memory_search

    with patch(
        "metronix.mcp.tools.memory_search._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(),
    ) as build_service:
        out = await metronix_memory_search(
            query="blocked", workspace_id="ws-a", agent_id="agent-a"
        )

    assert out["error"]["code"] == "AUTH_REQUIRED"
    build_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_list_with_agent_id_denies_before_memory_service_without_principal() -> None:
    from metronix.mcp.tools.memory_review_list import metronix_memory_review_list

    with patch(
        "metronix.mcp.tools.memory_review_list._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(),
    ) as build_service:
        out = await metronix_memory_review_list(workspace_id="ws-a", agent_id="agent-a")

    assert out["error"]["code"] == "AUTH_REQUIRED"
    build_service.assert_not_awaited()
