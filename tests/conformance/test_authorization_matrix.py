"""Cross-transport authorization conformance checks for issue #310."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from tests.conformance.fixtures import ConformanceGrants, bind_mcp_principal, rest_user


class _AuditStore:
    async def insert(self, row: object) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("principal_id", "workspace_id", "agent_id", "capability", "allowed"),
    [
        ("owner", "ws-a", "owner-agent", "read", True),
        ("delegate", "ws-a", "shared-agent", "read", True),
        ("delegate", "ws-a", "shared-agent", "write", False),
        ("delegate", "ws-a", "owner-agent", "read", False),
        ("delegate", "ws-b", "shared-agent", "read", False),
    ],
)
async def test_rest_and_direct_mcp_share_the_same_memory_decision(
    monkeypatch: pytest.MonkeyPatch,
    conformance_grants: ConformanceGrants,
    principal_id: str,
    workspace_id: str,
    agent_id: str,
    capability: str,
    allowed: bool,
) -> None:
    """A target swap must have the same outcome through REST and direct MCP."""
    from metronix.api.routes import memory
    from metronix.mcp.tools import _agent_access

    evaluator = conformance_grants.evaluator
    monkeypatch.setattr(memory, "get_authorization_evaluator", lambda: evaluator)
    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: evaluator)
    monkeypatch.setattr(_agent_access, "get_agent_access_audit_store", lambda: _AuditStore())

    user = rest_user(principal_id)
    if allowed:
        rest_decision = await memory.require_memory_access(
            user, workspace_id, agent_id, capability
        )
        assert rest_decision.allowed is True
    else:
        with pytest.raises(HTTPException) as rest_error:
            await memory.require_memory_access(user, workspace_id, agent_id, capability)
        assert rest_error.value.detail["code"] == "memory_access_denied"

    with bind_mcp_principal(principal_id):
        if allowed:
            mcp_decision = await _agent_access.require_agent_access(
                workspace_id, agent_id, capability
            )
            assert mcp_decision.allowed is True
        else:
            with pytest.raises(PermissionError, match="unauthorized agent memory access"):
                await _agent_access.require_agent_access(workspace_id, agent_id, capability)

    if workspace_id == "ws-b":
        assert conformance_grants.store.lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal_id, agent_id, allowed",
    [("owner", "owner-agent", True), ("delegate", "shared-agent", False)],
)
async def test_direct_mutation_and_action_execution_require_the_same_grant(
    conformance_grants: ConformanceGrants,
    principal_id: str,
    agent_id: str,
    allowed: bool,
) -> None:
    """Actions may not bypass the grant required by direct memory mutation."""
    from metronix.auth.policy import (
        AuthorizationRequest,
        Capability,
        ResourceType,
        Transport,
    )

    principal = conformance_grants.policy_principal(principal_id)
    mutation = await conformance_grants.evaluator.authorize(
        AuthorizationRequest(
            principal=principal,
            workspace_id="ws-a",
            agent_id=agent_id,
            resource_type=ResourceType.MEMORY,
            capability=Capability.WRITE,
            transport=Transport.MCP,
        )
    )
    execution = await conformance_grants.evaluator.authorize(
        AuthorizationRequest(
            principal=principal,
            workspace_id="ws-a",
            agent_id=agent_id,
            resource_type=ResourceType.ACTION,
            capability=Capability.EXECUTE,
            transport=Transport.ACTION,
        )
    )

    assert mutation.allowed is allowed
    assert execution.allowed is allowed
    assert execution.reason == mutation.reason


@pytest.mark.asyncio
async def test_denied_action_execution_has_no_external_side_effect(
    monkeypatch: pytest.MonkeyPatch, conformance_grants: ConformanceGrants, tmp_path
) -> None:
    """An ungranted target must be rejected before creating an MCP client."""
    from metronix.mcp.action_executor import ActionExecutor
    from metronix.mcp.action_store import PendingAction
    from metronix.mcp.config import MCPServerConfig
    from metronix.mcp.registry import MCPServerRegistry

    monkeypatch.setattr(
        "metronix.mcp.action_executor.get_authorization_evaluator",
        lambda: conformance_grants.evaluator,
    )
    registry = MCPServerRegistry(str(tmp_path))
    registry.add(MCPServerConfig(name="side-effect-sentinel", command="echo"))
    action = PendingAction(
        user_id="delegate",
        server_name="side-effect-sentinel",
        tool_name="write_memory",
        arguments={"content": "protected content must not be sent"},
        description="attempt a forbidden mutation",
        preview="",
        principal=conformance_grants.policy_principal("delegate"),
        workspace_id="ws-a",
        agent_id="owner-agent",
    )

    with patch("metronix.mcp.action_executor.MCPClient") as client:
        result = await ActionExecutor(registry).execute_async(action)

    assert result == {"success": False, "error": "Action is no longer authorized."}
    client.assert_not_called()
