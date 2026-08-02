"""Fail-closed authorization decisions for workspace-scoped agent access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from metronix.mcp.principal import MCPPrincipal


class AgentCapability(StrEnum):
    """Capabilities available for an agent within one workspace."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class AgentAccessGrantLike(Protocol):
    """Read-only active-grant shape consumed by the authorizer."""

    capability: str
    grant_type: str


class AgentAccessStore(Protocol):
    """Persistence boundary for active grants."""

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[AgentAccessGrantLike]:
        """Return active grants for an exact principal and agent target."""


@dataclass(frozen=True)
class AgentAccessGrant:
    """Persisted active grant projection."""

    capability: str
    grant_type: str


class PostgresAgentAccessStore:
    """PostgreSQL implementation of the active-grant lookup boundary."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[AgentAccessGrant]:
        async with self._engine.connect() as connection:
            rows = await connection.execute(
                text(
                    """
                    SELECT capability, grant_type
                    FROM agent_access_grants
                    WHERE workspace_id = :workspace_id
                      AND agent_id = :agent_id
                      AND principal_user_id = :principal_user_id
                      AND revoked_at IS NULL
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "principal_user_id": principal_user_id,
                },
            )
            return [AgentAccessGrant(capability=row[0], grant_type=row[1]) for row in rows]


@dataclass(frozen=True)
class AgentAccessDecision:
    """Content-free result of an agent-access evaluation."""

    decision_id: str
    allowed: bool
    reason: str
    policy_version: str = "agent-access-v1"


class AgentAccessAuthorizer:
    """Authorize verified MCP principals using explicit server-side grants."""

    def __init__(self, store: AgentAccessStore) -> None:
        self._store = store

    async def authorize(
        self,
        principal: MCPPrincipal | None,
        workspace_id: str,
        agent_id: str,
        capability: AgentCapability,
    ) -> AgentAccessDecision:
        if principal is None:
            return self._decision(False, "principal_required")
        if workspace_id not in principal.workspace_ids and "*" not in principal.workspace_ids:
            return self._decision(False, "workspace_not_granted")
        if principal.role == "admin":
            return self._decision(True, "admin_override")

        grants = await self._store.list_active_grants(workspace_id, agent_id, principal.user_id)
        allowed_grants = [grant for grant in grants if self._covers(grant.capability, capability)]
        if not allowed_grants:
            reason = "no_active_grant" if not grants else "capability_not_granted"
            return self._decision(False, reason)
        if any(grant.grant_type == "owner" for grant in allowed_grants):
            return self._decision(True, "owner_grant")
        return self._decision(True, "delegated_grant")

    @staticmethod
    def _covers(granted: str, requested: AgentCapability) -> bool:
        levels = {
            AgentCapability.READ: 1,
            AgentCapability.WRITE: 2,
            AgentCapability.ADMIN: 3,
        }
        try:
            return levels[AgentCapability(granted)] >= levels[requested]
        except ValueError:
            return False

    @staticmethod
    def _decision(allowed: bool, reason: str) -> AgentAccessDecision:
        return AgentAccessDecision(decision_id=uuid4().hex, allowed=allowed, reason=reason)
