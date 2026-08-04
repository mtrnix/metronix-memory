"""Unit coverage for the transport-neutral authorization policy."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class _Grant:
    capability: str
    grant_type: str = "delegate"


class _Store:
    def __init__(self, grants: list[_Grant]) -> None:
        self.grants = grants
        self.calls = 0

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[_Grant]:
        self.calls += 1
        return self.grants


class _RaisingStore:
    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[_Grant]:
        raise RuntimeError("database unavailable")


def _request(capability: object):
    from metronix.auth.policy import (
        AuthorizationRequest,
        PolicyPrincipal,
        ResourceType,
        Transport,
    )

    return AuthorizationRequest(
        principal=PolicyPrincipal("user-1", "editor", ("workspace-1",), "jwt"),
        workspace_id="workspace-1",
        agent_id="agent-1",
        resource_type=ResourceType.MEMORY,
        capability=capability,
        transport=Transport.MCP,
    )


@pytest.mark.asyncio
async def test_delegate_with_read_grant_cannot_write() -> None:
    from metronix.auth.policy import AuthorizationEvaluator, Capability

    decision = await AuthorizationEvaluator(_Store([_Grant("read")])).authorize(
        _request(Capability.WRITE)
    )

    assert decision.allowed is False
    assert decision.reason == "capability_not_granted"


@pytest.mark.asyncio
async def test_grant_lookup_failure_denies() -> None:
    from metronix.auth.policy import AuthorizationEvaluator, Capability

    decision = await AuthorizationEvaluator(_RaisingStore()).authorize(_request(Capability.READ))

    assert decision.allowed is False
    assert decision.reason == "grant_lookup_failed"


@pytest.mark.asyncio
async def test_ungranted_workspace_denies_without_lookup() -> None:
    from metronix.auth.policy import (
        AuthorizationEvaluator,
        AuthorizationRequest,
        Capability,
        PolicyPrincipal,
        ResourceType,
        Transport,
    )

    store = _Store([])
    decision = await AuthorizationEvaluator(store).authorize(
        AuthorizationRequest(
            principal=PolicyPrincipal("user-1", "editor", ("workspace-1",), "jwt"),
            workspace_id="workspace-2",
            agent_id="agent-1",
            resource_type=ResourceType.MEMORY,
            capability=Capability.READ,
            transport=Transport.REST,
        )
    )

    assert decision.allowed is False
    assert decision.reason == "workspace_not_granted"
    assert store.calls == 0


@pytest.mark.asyncio
async def test_action_execution_uses_the_target_agents_write_grant() -> None:
    from metronix.auth.policy import AuthorizationEvaluator, Capability, ResourceType

    request = _request(Capability.EXECUTE)
    request = request.__class__(
        **{**request.__dict__, "resource_type": ResourceType.ACTION, "transport": "action"}
    )
    decision = await AuthorizationEvaluator(_Store([_Grant("write")])).authorize(request)

    assert decision.allowed is True
