"""PostgreSQL conformance checks for expiring agent-access grants."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.auth.agent_access import PostgresAgentAccessStore
from metronix.auth.policy import (
    AuthorizationEvaluator,
    AuthorizationRequest,
    Capability,
    PolicyPrincipal,
    ResourceType,
    Transport,
)
from metronix.core.config import get_settings

pytestmark = pytest.mark.integration


async def test_expired_delegated_grant_is_not_authorized() -> None:
    """An expired write grant must not become an active delegation."""
    workspace_id = f"grant-expiry-{uuid4().hex[:8]}"
    agent_id = "shared-agent"
    principal_id = f"delegate-{uuid4().hex[:8]}"
    engine = create_async_engine(get_settings().postgres_dsn, pool_pre_ping=True)
    store = PostgresAgentAccessStore(engine)

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_access_grants (
                        id, workspace_id, agent_id, principal_user_id, capability,
                        grant_type, granted_by_user_id, expires_at
                    ) VALUES (
                        :id, :workspace_id, :agent_id, :principal_id, 'write',
                        'delegate', :principal_id, now() - interval '1 minute'
                    )
                    """
                ),
                {
                    "id": f"expired-{uuid4().hex}",
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "principal_id": principal_id,
                },
            )

        assert await store.list_active_grants(workspace_id, agent_id, principal_id) == []
        decision = await AuthorizationEvaluator(store).authorize(
            AuthorizationRequest(
                principal=PolicyPrincipal(principal_id, "editor", (workspace_id,), "jwt"),
                workspace_id=workspace_id,
                agent_id=agent_id,
                resource_type=ResourceType.MEMORY,
                capability=Capability.WRITE,
                transport=Transport.MCP,
            )
        )
        assert decision.allowed is False
        assert decision.reason == "no_active_grant"
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM agent_access_grants WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            )
        await engine.dispose()
