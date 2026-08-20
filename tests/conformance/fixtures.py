"""Shared, transport-neutral authorization fixtures for conformance tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from metronix.auth.policy import AuthorizationEvaluator, PolicyPrincipal
from metronix.core.models import Role, User
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal


@dataclass(frozen=True)
class Grant:
    """An active, server-issued agent access grant for a conformance scenario."""

    workspace_id: str
    agent_id: str
    principal_user_id: str
    capability: str
    grant_type: str


class GrantStore:
    """In-memory active-grant projection that records lookup targets."""

    def __init__(self, grants: list[Grant]) -> None:
        self._grants = grants
        self.lookups: list[tuple[str, str, str]] = []

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[Grant]:
        self.lookups.append((workspace_id, agent_id, principal_user_id))
        return [
            grant
            for grant in self._grants
            if (grant.workspace_id, grant.agent_id, grant.principal_user_id)
            == (workspace_id, agent_id, principal_user_id)
        ]


class ConformanceGrants:
    """The owner, delegate, and out-of-scope targets shared by every adapter."""

    def __init__(self) -> None:
        self.store = GrantStore(
            [
                Grant("ws-a", "owner-agent", "owner", "admin", "owner"),
                Grant("ws-a", "shared-agent", "delegate", "read", "delegate"),
            ]
        )
        self.evaluator = AuthorizationEvaluator(self.store)

    @staticmethod
    def policy_principal(principal_id: str) -> PolicyPrincipal:
        return PolicyPrincipal(principal_id, "editor", ("ws-a",), "jwt")


@pytest.fixture
def conformance_grants() -> ConformanceGrants:
    """Supply the exact same active grants to REST, MCP, and action checks."""
    return ConformanceGrants()


def rest_user(principal_id: str) -> User:
    """Build the REST representation of a shared fixture principal."""
    return User(id=principal_id, role=Role.EDITOR, workspace_ids=["ws-a"])


@contextmanager
def bind_mcp_principal(principal_id: str) -> Iterator[None]:
    """Bind the MCP representation of a shared fixture principal."""
    token = bind_principal(MCPPrincipal(principal_id, "editor", ("ws-a",)))
    try:
        yield
    finally:
        reset_principal(token)
