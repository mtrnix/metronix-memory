"""Authorization guard shared by MCP agent-memory tools."""

from __future__ import annotations

from functools import lru_cache

import structlog

from metronix.auth.agent_access import (
    AgentAccessDecision,
    AgentCapability,
    get_authorization_evaluator,
)
from metronix.auth.policy import (
    AuthorizationRequest,
    Capability,
    PolicyPrincipal,
    ResourceType,
    Transport,
)
from metronix.mcp.principal import get_current_principal
from metronix.storage.activity_pg import ActivityRow, ActivityStore

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_agent_access_audit_store() -> ActivityStore:
    """Return the append-only audit store for authorization decisions."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from metronix.core.config import get_settings

    return ActivityStore(create_async_engine(get_settings().postgres_dsn))


async def _record_decision(
    *,
    principal_id: str | None,
    workspace_id: str,
    agent_id: str,
    capability: AgentCapability | str,
    decision: AgentAccessDecision,
) -> None:
    """Persist a content-free, append-only authorization decision."""
    await get_agent_access_audit_store().insert(
        ActivityRow(
            workspace_id=workspace_id,
            agent_id=agent_id,
            event_type="agent.access_decision",
            event_data={
                "principal_id": principal_id,
                "capability": str(capability),
                "transport": Transport.MCP,
                "decision_id": decision.decision_id,
                "policy_version": decision.policy_version,
                "outcome": decision.allowed,
                "reason": decision.reason,
            },
        )
    )


async def _best_effort_denial_audit(**kwargs: object) -> None:
    """Record a denial without ever weakening the fail-closed response."""
    try:
        await _record_decision(**kwargs)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - denial must stay an authorization denial
        logger.error("agent_access.audit_failed", exc_info=True)


async def require_agent_access(
    workspace_id: str, agent_id: str, capability: AgentCapability | str
) -> AgentAccessDecision:
    """Require an authenticated principal before an agent-memory operation."""
    principal = get_current_principal()
    if principal is None:
        decision = AgentAccessDecision("missing-principal", False, "principal_required")
        await _best_effort_denial_audit(
            principal_id=None,
            workspace_id=workspace_id,
            agent_id=agent_id,
            capability=capability,
            decision=decision,
        )
        raise PermissionError("unauthorized agent memory access")

    requested_capability = Capability(capability)
    decision = await get_authorization_evaluator().authorize(
        AuthorizationRequest(
            principal=PolicyPrincipal.from_mcp(principal),
            workspace_id=workspace_id,
            agent_id=agent_id,
            resource_type=ResourceType.MEMORY,
            capability=requested_capability,
            transport=Transport.MCP,
        )
    )
    if not decision.allowed:
        await _best_effort_denial_audit(
            principal_id=principal.user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            capability=capability,
            decision=decision,
        )
        raise PermissionError("unauthorized agent memory access")

    await _record_decision(
        principal_id=principal.user_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        capability=capability,
        decision=decision,
    )
    logger.info(
        "agent_access.decision",
        workspace_id=workspace_id,
        agent_id=agent_id,
        capability=str(capability),
        principal_id=principal.user_id,
        decision_id=decision.decision_id,
        policy_version=decision.policy_version,
        outcome=True,
        reason=decision.reason,
    )
    return decision
