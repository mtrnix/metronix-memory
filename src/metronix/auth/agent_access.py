"""Fail-closed authorization decisions for workspace-scoped agent access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from metronix.auth.policy import (
    AuthorizationDecision,
    AuthorizationEvaluator,
    AuthorizationRequest,
    Capability,
    PolicyPrincipal,
    ResourceType,
    Transport,
)
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


@lru_cache(maxsize=1)
def get_authorization_evaluator() -> AuthorizationEvaluator:
    """Return the process-wide evaluator backed by active grant storage."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from metronix.core.config import get_settings

    engine = create_async_engine(get_settings().postgres_dsn)
    return AuthorizationEvaluator(PostgresAgentAccessStore(engine))


AgentAccessDecision = AuthorizationDecision


class AgentAccessAuthorizer:
    """Authorize verified MCP principals using explicit server-side grants."""

    def __init__(self, store: AgentAccessStore) -> None:
        self._evaluator = AuthorizationEvaluator(store)

    async def authorize(
        self,
        principal: MCPPrincipal | None,
        workspace_id: str,
        agent_id: str,
        capability: AgentCapability,
    ) -> AgentAccessDecision:
        return await self._evaluator.authorize(
            AuthorizationRequest(
                principal=PolicyPrincipal.from_mcp(principal) if principal is not None else None,
                workspace_id=workspace_id,
                agent_id=agent_id,
                resource_type=ResourceType.MEMORY,
                capability={
                    AgentCapability.READ: Capability.READ,
                    AgentCapability.WRITE: Capability.WRITE,
                    AgentCapability.ADMIN: Capability.ADMINISTER,
                }[capability],
                transport=Transport.MCP,
            )
        )
