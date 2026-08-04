"""Unit coverage for server-side agent ownership and delegation decisions."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from metronix.mcp.principal import MCPPrincipal


@dataclass(frozen=True)
class _Grant:
    workspace_id: str
    agent_id: str
    principal_user_id: str
    capability: str
    grant_type: str


class _Store:
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


@pytest.mark.asyncio
async def test_owner_grant_allows_write() -> None:
    from metronix.auth.agent_access import AgentAccessAuthorizer, AgentCapability

    decision = await AgentAccessAuthorizer(
        _Store([_Grant("ws-a", "agent-a", "u1", "admin", "owner")])
    ).authorize(
        MCPPrincipal("u1", "editor", ("ws-a",)),
        "ws-a",
        "agent-a",
        AgentCapability.WRITE,
    )

    assert decision.allowed is True
    assert decision.reason == "owner_grant"
    assert decision.policy_version == "authz-v1"


@pytest.mark.asyncio
async def test_read_delegate_cannot_write() -> None:
    from metronix.auth.agent_access import AgentAccessAuthorizer, AgentCapability

    decision = await AgentAccessAuthorizer(
        _Store([_Grant("ws-a", "agent-a", "u2", "read", "delegate")])
    ).authorize(
        MCPPrincipal("u2", "editor", ("ws-a",)),
        "ws-a",
        "agent-a",
        AgentCapability.WRITE,
    )

    assert decision.allowed is False
    assert decision.reason == "capability_not_granted"


@pytest.mark.asyncio
async def test_workspace_admin_can_manage_unowned_agent() -> None:
    from metronix.auth.agent_access import AgentAccessAuthorizer, AgentCapability

    decision = await AgentAccessAuthorizer(_Store([])).authorize(
        MCPPrincipal("admin", "admin", ("ws-a",)),
        "ws-a",
        "legacy-agent",
        AgentCapability.ADMIN,
    )

    assert decision.allowed is True
    assert decision.reason == "admin_override"


@pytest.mark.asyncio
async def test_missing_principal_is_denied_without_grant_lookup() -> None:
    from metronix.auth.agent_access import AgentAccessAuthorizer, AgentCapability

    store = _Store([])
    decision = await AgentAccessAuthorizer(store).authorize(
        None,
        "ws-a",
        "agent-a",
        AgentCapability.READ,
    )

    assert decision.allowed is False
    assert decision.reason == "principal_required"
