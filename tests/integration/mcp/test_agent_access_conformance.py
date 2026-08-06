"""Direct MCP conformance checks for explicit agent ownership and delegation."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from metronix.auth.agent_access import AgentAccessAuthorizer
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal


@dataclass(frozen=True)
class _Grant:
    workspace_id: str
    agent_id: str
    principal_user_id: str
    capability: str
    grant_type: str


class _GrantStore:
    def __init__(self, grants: list[_Grant]) -> None:
        self._grants = grants

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[_Grant]:
        return [
            grant
            for grant in self._grants
            if (grant.workspace_id, grant.agent_id, grant.principal_user_id)
            == (workspace_id, agent_id, principal_user_id)
        ]


class _AuditStore:
    async def insert(self, row: object) -> None:
        return None


@pytest.fixture
def evaluator(monkeypatch: pytest.MonkeyPatch) -> AgentAccessAuthorizer:
    from metronix.mcp.tools import _agent_access

    authorizer = AgentAccessAuthorizer(
        _GrantStore(
            [
                _Grant("ws-a", "owner-agent", "owner", "admin", "owner"),
                _Grant("ws-a", "shared-agent", "delegate", "read", "delegate"),
            ]
        )
    )
    monkeypatch.setattr(_agent_access, "get_agent_access_authorizer", lambda: authorizer)
    monkeypatch.setattr(_agent_access, "get_agent_access_audit_store", lambda: _AuditStore())
    return authorizer


@pytest.mark.asyncio
async def test_delegated_read_can_call_search_for_the_explicitly_shared_agent(
    evaluator: AgentAccessAuthorizer,
) -> None:
    from metronix.mcp.tools.memory_search import metronix_memory_search

    service = AsyncMock()
    service.search = AsyncMock(return_value=[])
    token = bind_principal(MCPPrincipal("delegate", "editor", ("ws-a",)))
    try:
        with patch(
            "metronix.mcp.tools.memory_search._memory_deps.build_memory_service_for_workspace",
            new=AsyncMock(return_value=service),
        ):
            out = await metronix_memory_search(
                query="recall", workspace_id="ws-a", agent_id="shared-agent"
            )
    finally:
        reset_principal(token)

    assert out["count"] == 0
    service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_delegated_read_cannot_write_or_swap_to_another_agent(
    evaluator: AgentAccessAuthorizer,
) -> None:
    from metronix.mcp.tools.memory_search import metronix_memory_search
    from metronix.mcp.tools.memory_store import metronix_memory_store

    search_service = AsyncMock()
    store_service = AsyncMock()
    token = bind_principal(MCPPrincipal("delegate", "editor", ("ws-a",)))
    try:
        with (
            patch(
                "metronix.mcp.tools.memory_search._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=search_service),
            ) as build_search,
            patch(
                "metronix.mcp.tools.memory_store._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=store_service),
            ) as build_store,
        ):
            swapped = await metronix_memory_search(
                query="recall", workspace_id="ws-a", agent_id="owner-agent"
            )
            write = await metronix_memory_store(
                content="attempted mutation", workspace_id="ws-a", agent_id="shared-agent"
            )
    finally:
        reset_principal(token)

    assert swapped["error"]["code"] == "AUTH_REQUIRED"
    assert write["error"]["code"] == "AUTH_REQUIRED"
    build_search.assert_not_awaited()
    build_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_actions_use_the_same_agent_capability_decision(
    evaluator: AgentAccessAuthorizer,
) -> None:
    from metronix.mcp.tools.memory_review_list import metronix_memory_review_list
    from metronix.mcp.tools.memory_review_resolve import metronix_memory_review_resolve

    service = AsyncMock()
    token = bind_principal(MCPPrincipal("delegate", "editor", ("ws-a",)))
    try:
        with (
            patch(
                "metronix.mcp.tools.memory_review_list._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=service),
            ) as build_list,
            patch(
                "metronix.mcp.tools.memory_review_resolve._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=service),
            ) as build_resolve,
        ):
            list_out = await metronix_memory_review_list(
                workspace_id="ws-a", agent_id="owner-agent"
            )
            resolve_out = await metronix_memory_review_resolve(
                review_id="review-1", action="keep", workspace_id="ws-a", agent_id="shared-agent"
            )
    finally:
        reset_principal(token)

    assert list_out["error"]["code"] == "AUTH_REQUIRED"
    assert resolve_out["error"]["code"] == "AUTH_REQUIRED"
    build_list.assert_not_awaited()
    build_resolve.assert_not_awaited()
